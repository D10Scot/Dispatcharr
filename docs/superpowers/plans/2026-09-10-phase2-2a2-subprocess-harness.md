# Phase 2 PR 2a-2 — The Subprocess Harness and the Coverage Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend suite a capability it has never had — a test that spawns a **real**
subprocess through the relay's own production spawn path and streams **real** MPEG-TS bytes from an
in-process fake upstream — and ship `scripts/coverage_live_path.sh`, the one reproducible command
2a-3 … 2a-6 quote their coverage numbers from.

**Architecture:** The harness is a Python package under `apps/proxy/live_proxy/tests/harness/`. It
has four parts: a **fake upstream** (`http.server.ThreadingHTTPServer`, no new dependency) serving a
looping synthetic TS asset with eight injectable faults ported from `e2e-upstream/src/faults.ts`; a
**process stand-in** — a small Python program installed into a temp directory *under the name
`ffmpeg`* and put first on `PATH`, so the relay's unmodified `shutil.which("ffmpeg")` resolves to it
and `os.posix_spawn` runs it for real; a **relay bring-up base class** built on
`django.test.LiveServerTestCase`, which gives real Redis, real committed rows visible to the relay's
background OS threads, and a real HTTP control plane at the other end of `/api/relay/…`; and a
**real-ffmpeg escape hatch** for the fMP4 work 2a-6 owns. `scripts/coverage_live_path.sh` runs the
three Gate 2 labels one process each under `coverage run --parallel-mode`, `coverage combine`s them
and prints the percentage, refusing to report a number assembled from any other measurement shape.

**Tech Stack:** Python 3.13, Django 6 (`LiveServerTestCase`, `TransactionTestCase` semantics),
`coverage` 7.16 (already a dependency, `pyproject.toml:45`), `requests` (already a dependency),
`http.server`/`socketserver`/`threading` from the standard library, bash. **No new dependency in
`pyproject.toml`, `uv.lock`, `e2e/package.json` or any Dockerfile.**

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § Stage 2a › Gate 2 — 80%
statement coverage; § Stage 2a › The subprocess harness — 2a's named deliverable; § Stage 2a ›
The seven PRs, row `2a-2`; § Verified facts this design rests on; § Testing.

**Branch:** `migration/phase2a-subprocess-harness` (worktree
`/Users/dion/git/Dispatcharr/.worktrees/phase2-2a2`), off `main` at `e62ab428`.

---

## Branch base

This branch is cut from `main` at `e62ab428` (2a-1, `docs/relay-parity-matrix.md` + its guard,
merged as #223). It depends on 2a-1 only in the sense that later PRs cite matrix rows; **2a-2 owns
no matrix row, closes none, and edits neither `docs/relay-parity-matrix.md` nor
`e2e/tests/guards/parity-matrix.{ts,spec.ts}`.**

The spec this plan implements lives on a **different branch** (`.worktrees/phase2-spec`, Phase 2
PR 0, open as #225) and is not present in this worktree. That is deliberate and does not block:
every fact from the spec that the work needs is carried below. If you want to read it anyway it is
at
`/Users/dion/git/Dispatcharr/.worktrees/phase2-spec/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`
— read-only; never edit it from here.

**This plan file is already committed on this branch** by the planning pass. Every other file in
§ File structure is yours to create or modify.

**Every `file:line` and every number this plan quotes was verified against this worktree and against
a live `dispatcharr-testrunner` container on 2026-09-10.** Line numbers drift; the tree wins. Where
a step says "verify", it means run the command given and use what it answers, not what this plan
says.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **The branch is `migration/**`, so the full E2E and lifecycle matrices run on it.**
  `e2e-tests.yml` runs every Playwright project including `lifecycle-upgrade` and ignores its path
  filter; `lifecycle-tests.yml` runs both bash suites. That is a cost this PR pays for its branch
  name, not a signal that it touches those surfaces — it touches none of them.
- **No production code changes.** Nothing under `apps/proxy/live_proxy/` outside `tests/`, nothing
  under `apps/channels/`, `core/`, `dispatcharr/`, `docker/`. See § The seam decision for why this
  PR needs none. **If a task starts to need a production edit, stop and report** — that is a change
  to the seam decision, not a detail.
- **No workflow file is edited** — settled, not assumed. The CI wiring for the coverage gate, the
  floor file and the blocking behaviour are **2a-7's**, explicitly (spec § The seven PRs). A
  non-blocking matrix step added here would have to be reworked into a blocking one at 2a-7 while
  carrying the zizmor zero-findings ratchet through five intervening PRs, for a number 2a-3 … 2a-6
  can get by running the script locally. **They run it and paste its output into their PR
  descriptions**; Task 1's shape-stamping check is exactly what makes a pasted number trustworthy.
  If a task appears to need a workflow edit, it is out of scope — stop and report.
- **`CELERY_TASK_ALWAYS_EAGER` is off globally and stays off.** `post_save` on `M3UAccount` calls
  `.delay()`; the harness's fixtures create an `M3UAccount`, so the task is enqueued to the real
  Redis broker and never runs. That is correct and is what `apps/proxy/tests/test_next_source_resolution.py:115`
  already does. Do not add `@override_settings(CELERY_TASK_ALWAYS_EAGER=True)` anywhere in this PR.
- **Never pass `--settings=dispatcharr.settings` to `manage.py test`.** `manage.py:11` rewrites the
  settings module to `dispatcharr.settings_test` for the `test` command only; overriding it points
  the suite at the production database.
- **Tests need Postgres and Redis.** Redis is flushed before every backend run by the hook and by
  CI, and the whole package runs, not just the edited module.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the `PreToolUse` hook matches on command text and
  blocks any single call containing both verbs, and trips on a heredoc that merely contains them.
- **Every `gh` command carries `--repo D10Scot/Dispatcharr`.** Without it `gh` resolves to
  upstream's public tracker (`docs/agents/issue-tracker.md`).
- **`scripts/check_credential_logging.py` runs on every edited `*.py`, including test files** — it
  is given the edited path and has no test exclusion (`scripts/check_credential_logging.py:279-289`).
  The harness handles URLs constantly. **Do not pass a URL, path, header or credential to a
  `logger.*` call anywhere in this PR.** `print()` is fine and is what the harness and
  `scripts/capture_ffmpeg_stderr.py` use: the check matches only a receiver whose name ends in
  `logger` calling one of `info`/`debug`/`warning`/`error`/`exception`, so a bare `print` or a
  `logging.info` on the module is outside its scope — verified by reading the file, not assumed.
  Stay inside `print()` anyway rather than relying on that gap.
- **Commit trailers.** Every commit in this PR ends with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
  ```

---

## The seam decision — settled here, as the spec requires

The spec (§ "What the harness must decide") leaves 2a-2's plan to choose among three ways to reach
the ≈827 subprocess-gated statements, and records the choice as this PR's own. **The choice is
(b), real subprocesses throughout — and the finding that makes it cheap is that "a real subprocess"
does not have to be a real `ffmpeg`.**

**The decision.** Every test in stage 2a that touches a spawn drives the relay's *unmodified*
`os.posix_spawn` call sites and gets a **real child process**. Which program that child runs is
chosen by the same two production mechanisms the relay already uses to pick one, so no production
code changes and no seam is extracted:

1. **`StreamProfile.command` / `parameters` are a database row.**
   `core/models.py:137-160`'s `build_command()` is `[self.command] + [substituted parameters]` —
   fully data-driven. `apps/proxy/live_proxy/input/manager.py:747` takes it verbatim and
   `:793`'s `os.posix_spawn` runs it. Same for the output side:
   `apps/proxy/live_proxy/output/profile/manager.py:88` spawns `self.command`, built by
   `core/models.py:200-203` from an `OutputProfile` row.
2. **`PATH`.** The one command that *is* hard-coded — `FFMPEG_REMUX_CMD` at
   `apps/proxy/live_proxy/output/fmp4/manager.py:32`, whose first element is the bare string
   `"ffmpeg"` — is resolved by `shutil.which(cmd[0])` inside `posix_spawn_proc`
   (`apps/proxy/live_proxy/utils.py:130`, the `executable = shutil.which(cmd[0]) or cmd[0]` line).
   A harness directory placed first on `PATH` containing an executable named `ffmpeg` therefore
   redirects that spawn too, with no patch. It also makes
   `input/manager.py`'s parser routing correct: `self.stream_command = stream_profile.command`
   feeds a `{'ffmpeg': 'ffmpeg', 'cvlc': 'vlc', …}` lookup, so a profile whose `command` is the
   literal string `ffmpeg` selects the ffmpeg log parser — which rows 1, 4 and 6 need — while the
   binary that actually runs is the harness's.

**Measured, in the `dispatcharr-testrunner` container on 2026-09-10:** a spawn of the Python
stand-in through the production `posix_spawn` pipe plumbing, to first stderr line *and* first stdout
bytes, is **6.5–8.1 ms** over five runs. A full relay bring-up — real `ProxyServer`, real Redis,
`initialize_channel`, real spawn, real TS bytes through the real `StreamBuffer` to `index == 2` —
completed in **0.4 s**. Spawn cost is not the constraint; wall-clock for time-gated *behaviour* is,
and § Keeping the suite fast below says how that is bounded.

**Why not (a), a process fake at `posix_spawn_proc` plus an extracted seam in `input/manager.py`.**
Three reasons, in order of weight.

1. **It buys nothing this buys, and costs the thing the harness is named for.** A `_Proc`-shaped
   fake makes `posix_spawn_proc` and `_Proc` themselves (~90 statements in `utils.py`, which sits at
   28.2%) and `input/manager.py`'s `_SpawnedProcess` (`:813`) permanently unreachable *by
   construction* — they are exactly the code the fake replaces. That code is the pipe plumbing,
   the `waitpid` reaping and the `terminate`/`kill` escalation `CLAUDE.md` warns must never be
   "simplified back to `Popen`", i.e. the most fragile code in the file. The stand-in exercises all
   of it for real while still giving byte-exact control of stdout, stderr, exit code and exit
   timing — strictly more control than a real ffmpeg, and strictly more coverage than a fake.
2. **It requires a production-code change inside a stage scoped to tests, and now there is no
   reason to pay for one.** The spec is careful to say the extraction would be small and would not
   be the `Popen` simplification `CLAUDE.md` forbids — both true. But the justification for it was
   that `input/manager.py` "shares no seam with the helper and there is nothing to patch but
   `os.posix_spawn` globally." That framing looks for a seam *inside the process*. The seam is
   outside it: the command comes from a DB row and the binary from `PATH`, and both are production
   mechanisms an operator uses today.
3. **The composition rule cuts the same way.** The spec's rule — "drive the relay through its HTTP
   surface against real dependencies … never against mocks of `server.py`'s or `input/manager.py`'s
   internals" — is about what a test *asserts on*. A `_Proc` fake would not violate it in letter,
   since ffmpeg is a genuine external dependency and a double for it is legitimate. But `CLAUDE.md`
   § Testing names the current gap precisely — "ffmpeg lifecycle and stderr parsing run only against
   hand-written strings" — and a fake fed canned stderr is the same object one layer out. The
   stand-in closes the gap at the layer the gap is at: **the process boundary is real; only the
   program on the far side of it is chosen.**

**The argument that outlasts this stage: the stand-in is language-agnostic, and the fake at the
seam would not have been.** A `_Proc` fake is a Python object implementing a Python duck type; it
dies with `apps/proxy/live_proxy/` in 2d and teaches 2c nothing it can run. The stand-in is an
executable on `PATH` that speaks the ffmpeg contract — argv in, TS on stdout, progress on stderr,
an exit code — so **2c's Go relay spawns it unchanged**, with `exec.Command("ffmpeg", …)` finding it
by the same `PATH` mechanism, and the fault vocabulary and the stderr corpus transfer with it
instead of being reimplemented in Go from `input/manager.py`'s prose. That is what the spec means by
"this harness is not throwaway" and by "having already named the fault vocabulary in Python fixtures
gives the Go author a spec to copy." It is a stronger reason for option (b) than the coverage
arithmetic: the coverage argument says the fake reaches fewer statements, this one says the fake
reaches none of stage 2c at all.

**Why not (c), patching `os.posix_spawn` globally.** It is the same loss as (a) with an extra
hazard: `os.posix_spawn` is process-global and the relay's spawns happen on background OS threads
(`server.py:851` starts `stream_manager.run` on a `threading.Thread`), so a patch installed by one
test can be live while another test's thread spawns. It also makes the file-action tuples — the
`POSIX_SPAWN_OPEN`/`DUP2`/`CLOSE` list that is the actual subject of `input/manager.py:793-803` —
assertion targets rather than executed code, which is the inverse of what stage 2a is for.

**Where a *real ffmpeg* is still required, and it is a narrow place.** Only where the bytes
themselves must be a real remuxer's output: `output/fmp4/generator.py` and `output/fmp4/buffer.py`
parse `moof`/`moov` boxes (`MOOF_BOX_TYPE = b"moof"`, `output/fmp4/manager.py:63`) that only a real
`-f mp4 -movflags frag_keyframe+…` remux produces. That is **2a-6's** scope. This PR ships the
capability (`require_real_ffmpeg()` and `build_real_ts_asset()`, Task 6) and one smoke test using
it, marked skip-if-unavailable — see the ffmpeg finding in § Verified facts for why "unavailable"
is a real state in this repo's own containers today.

**The stated rule, for every 2a PR that follows.** Write it into the harness README (Task 7):

> **Every spawn is real.** The child program is the stand-in when the test's subject is the relay's
> *reaction* to what a process said or did — a stderr line, an exit code, an exit moment, a byte
> rate — because those must be exact and a real ffmpeg cannot be made exact on demand. The child
> program is real `ffmpeg` when the test's subject is the *bytes a remuxer produces*. It is never a
> Python object standing in for a process.
>
> **And every line the stand-in writes to stderr came out of a real ffmpeg.** The corpus in
> `harness/fixtures/ffmpeg_stderr/` was captured from ffmpeg 8.1.2 against a real upstream (Task 4);
> the stand-in replays it. A hand-written progress line is legitimate only for a shape real ffmpeg
> cannot be made to emit on demand, and carries a comment saying which shape and why. Without that
> rule, option (b) collapses straight back into the gap `CLAUDE.md` § Testing names — "ffmpeg
> lifecycle and stderr parsing run only against hand-written strings there" — with rows 1-6
> asserting that our parser parses our own fiction.

---

## Verified facts this plan rests on

Each was established by running the command shown, in the `dispatcharr-testrunner` container
(`/repo` = this repository at `a948cd8a`; `e62ab428` adds only `docs/` and `e2e/` files, none of
which affect any measurement here).

### F1 — The spec's Gate 2 invocation, taken verbatim, does not produce the spec's number

The spec's "Corrected shape" block is:

```bash
coverage run --include='apps/proxy/live_proxy/*,…' \
  manage.py test apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests
```

Run from the repository root, coverage auto-discovers `.coveragerc`, which sets
`source = apps, core, dispatcharr` (`.coveragerc:4`). Coverage then **ignores `--include` at run
time** and says so:

```
coverage/inorout.py:513: CoverageWarning: --include is ignored because --source is set
  (include-ignored)
```

The data file that results holds **212 files / 38,418 statements / 30%**, not 7,978 / 3,977 / 50%.
The published figure is only reachable because (i) `.coveragerc`'s `omit = */tests/*` *does* apply
at run time and keeps the 20 test modules out, and (ii) a **report-time** `--include` filter — which
the spec's snippet does not contain — narrows the report to the ten modules. **This is a defect in
the spec's snippet, not in its numbers**; the numbers are right, the command under them is not.
Task 1 replaces it with a self-contained rcfile that needs no ambient `.coveragerc`.

### F2 — The rcfile shape that reproduces the spec exactly

`[run] source = apps/proxy` + `[run] omit = */tests/*` + `[report] include = <the ten patterns>` +
`[report] omit = */tests/*`, run per label with `parallel = True` and combined, produces:

```
TOTAL   7978   3977   50%          (coverage json: 50.150413637503135)
```

— the spec's 7,978 / 3,977 / 50.2% to the statement, with **zero** coverage warnings, and every
per-file line matching § Verified facts (`server.py` 1490/977, `input/manager.py` 1248/771,
`output/fmp4/generator.py` 219/195, `input/http_streamer.py` 101/101, and the rest).

**`source` cannot be replaced by `[run] include`.** Measured: with `[run] include` and no `source`,
the total drops to **7,877 / 3,876** — 101 statements short. The 101 are
`apps/proxy/live_proxy/input/http_streamer.py`, which no test imports: `source` triggers coverage's
unexecuted-file walk and reports it at 0%, while a run-time `include` filter only records files that
actually execute, so the file vanishes from the denominator entirely. A denominator that shrinks
when a file goes completely untested is the wrong shape for a ratchet. **Task 1 uses `source`.**

### F3 — Three labels are the whole measurement; the whole run costs 15 seconds

`apps.proxy.tests`, `apps.proxy.live_proxy.tests` and `apps.channels.tests`, each its own process,
with `redis-cli flushall` between them: **15.2 s wall** end to end including `combine` and `report`.
The spec's own control run over all 16 labels moved `live_proxy` by zero statements.

### F4 — `ffmpeg` is present in both test containers and **cannot run** in either

```
$ docker exec dispatcharr-testrunner which ffmpeg
/usr/local/bin/ffmpeg
$ docker exec dispatcharr-testrunner ffmpeg -version
ffmpeg: symbol lookup error: ffmpeg: undefined symbol: rist_peer_config_defaults_set_versioned
```

The image carries two `librist`: `/usr/local/lib/librist.so.4.11.0` (what ffmpeg was linked
against) and the distro's `/usr/lib/<arch>/librist.so.4.3.1`, pulled in by the `vlc` install. The
`ld.so.conf.d` ordering puts the multiarch directory first, so the loader picks 4.3.1, which lacks
the symbol. `LD_LIBRARY_PATH=/usr/local/lib ffmpeg -version` works and prints `ffmpeg version
8.1.2`.

Production is unaffected because `docker/entrypoint.sh:102` does `export
LD_LIBRARY_PATH='/usr/local/lib'`. **Neither test context runs that entrypoint**: the hook container
is started with `--entrypoint sleep` (`.claude/hooks/start-test-container.sh`), and
`backend-tests.yml`'s container block sets `options: --entrypoint ""`. The image config itself
carries no `LD_LIBRARY_PATH` (`docker inspect … .Config.Env`), and `scripts/ci_bootstrap_backend.sh`
does not set one.

**Consequences the plan honours:** (i) nothing in the default harness path depends on ffmpeg —
Tasks 2–5 use the stand-in and a synthetic asset; (ii) `require_real_ffmpeg()` (Task 6) sets
`LD_LIBRARY_PATH=/usr/local/lib` for the probe and for anything it spawns, and **skips** the test
with a message naming this finding when the probe still fails, so the suite never turns red on an
image that happens to link differently.

### F5 — The relay's background workers are real OS threads, and the test process is **not**
gevent-monkey-patched

`monkey.patch_all()` reaches the application only through `dispatcharr/gevent_patch.py`, which is
imported by uWSGI ini files (`docker/uwsgi*.ini`) and by `debian_install.sh:363`. `manage.py`,
`dispatcharr/settings_test.py` and `dispatcharr/test_runner.py` import none of it — verified by
reading all three in full. Under `manage.py test` the process runs plain CPython, and the relay's
workers are ordinary daemon threads: `server.py:2192` (cleanup), `:467` (Redis event listener),
`:851` (per-channel stream manager), `input/manager.py:396` (health monitor), `:904` (stderr
reader). They run concurrently and pre-emptively; nothing needs a gevent hub to schedule them.

`gevent.sleep()` inside those threads (e.g. `input/manager.py:1565`) still works unpatched — gevent
creates a hub per thread — and really sleeps, which is why § Keeping the suite fast compresses the
intervals rather than mocking the clock.

### F6 — Committed rows, not transactions: the harness base class must be a `TransactionTestCase`

The relay reads the DB from its own threads with their own connections
(`input/manager.py:730`'s `get_stream_object(self.channel_id)` runs on the stream-manager thread).
A `django.test.TestCase` wraps the test in a transaction on the *main* thread's connection, so rows
created there are invisible to those threads. `LiveServerTestCase` is a `TransactionTestCase`
subclass and commits, which is why Task 5 uses it — the live server is a second, independent reason,
not the only one.

### F7 — The end-to-end bring-up works, today, with no production change

Prototyped on 2026-09-10 in the container: a `ThreadingTCPServer` serving 188-byte TS packets, a
Python stand-in written to a temp dir as `ffmpeg` and prepended to `PATH`, a `StreamProfile(command="ffmpeg",
parameters="-i {streamUrl}")`, a `Channel` row, then `ProxyServer.get_instance()` and
`initialize_channel(url, uuid, transcode=True)`. Result:

```
which ffmpeg: /tmp/tmpdp_t3ir9/ffmpeg
initialize_channel: True
buffer index: 2      elapsed 0.4
stream manager: True  pid: 8163
```

Two observations the plan acts on. **(a)** With no control plane reachable, the relay logs
`Could not post 1 relay event(s): /api/relay/events unreachable` and
`control plane unreachable for release; profile slot stays counted` — it degrades, it does not fail.
Task 5 removes the degrade by pointing `DISPATCHARR_INTERNAL_API_BASE_URL` at the live server.
**(b)** Without a `Stream` row it warns `No stream_id provided` — Task 5's fixture creates real
`M3UAccount`/`M3UAccountProfile`/`Stream`/`ChannelStream` rows, copying the recipe already proven at
`apps/proxy/tests/test_next_source_resolution.py:110-144`.

### F8 — Every threshold the harness needs to compress is reachable without mocking

- `buffering_timeout` (default 15) and `buffering_speed` (default 1.0) are `CoreSettings`
  `proxy_settings` values (`apps/proxy/config.py:51-52`), snapshotted into the manager at
  `input/manager.py:60-61` — i.e. at `StreamManager.__init__`, which is parity-matrix row 5. Write
  the setting, call `TSConfig.clear_proxy_settings_cache()` (`apps/proxy/config.py:33`), then start
  the channel. This is the production lever, not a mock.
- `health_check_interval` is `ConfigHelper.get('HEALTH_CHECK_INTERVAL', 5)`
  (`input/manager.py:77`) and `CONNECTION_TIMEOUT` is a class attribute on `BaseConfig`
  (`apps/proxy/config.py:13`), read through `getattr(Config, …)` at
  `input/manager.py:1506`. Both are compressible with `unittest.mock.patch.object` on the config
  class.
- **The ring buffer's chunk size is ~256 KB, not the ~1 MB `CLAUDE.md` states**, and it is
  compressible. `input/buffer.py:42` reads `ConfigHelper.get('BUFFER_CHUNK_SIZE', TS_PACKET_SIZE *
  5644)`, which is `getattr(Config, 'BUFFER_CHUNK_SIZE', …)` — and `BaseConfig.BUFFER_CHUNK_SIZE`
  **exists**, at `apps/proxy/config.py:15`, as `188 * 1361` = 255,868 bytes. The `5644` fallback
  therefore never fires. This matters to every harness test: a client sees nothing until a whole
  chunk closes (`input/buffer.py:97-100`), so a test that wants bytes quickly either lets the
  upstream run at loopback speed (the harness default, `rate=None`) or patches the class attribute
  down, e.g. `patch.object(TSConfig, 'BUFFER_CHUNK_SIZE', TS_PACKET_SIZE * 10)`. **This is a
  `CLAUDE.md` inaccuracy, not a code defect** — report it, do not fix it here.
- `max_unhealthy_checks = 3`, `action_cooldown = 30` and `stable_time >= 30` are **bare literals**
  in `_monitor_health` (`input/manager.py:1512`, `:1513`, `:1536`) and cannot be compressed. Budget
  `3 × health_check_interval` for any dead-air test, and note that `action_cooldown` bounds how fast
  a *second* health action can fire in one test.

### F9 — Routing and hooks

- `dispatcharr/test_discovery.py:41` routes `apps/proxy/live_proxy/` to **both**
  `apps.proxy.live_proxy` and `apps.channels`. New files under
  `apps/proxy/live_proxy/tests/` therefore need **no** `_PATH_ALIASES` entry and no change to
  `tests/test_ci_test_routing.py`.
- `scripts/coverage_live_path.sh` matches neither `_SHARED_PATH_PREFIXES`
  (`dispatcharr/test_discovery.py:10-18`) nor any app prefix, so it selects no labels on its own.
  That is correct — nothing imports it — and needs no routing entry either. This PR also adds test
  files, so the backend matrix runs regardless.
- The `PostToolUse` hook runs the whole `apps.proxy.live_proxy` + `apps.channels` packages when you
  edit a `tests/test_*.py`. It does **not** run tests when you edit a harness module
  (`harness/upstream.py` is not `test_*`); only `scripts/check_credential_logging.py` fires there.
  **After every harness-module edit, run the label yourself** (§ Verification command).

---

## Keeping the suite fast

The backend baseline is 2,212 tests in 28.5 s across 16 labels, and the commit hook runs whole
packages. Budget and mechanism:

- **Budget for this PR: ≤ 6 s added to the `apps.proxy.live_proxy` label. ≤ 15 s added across all of
  stage 2a is a hard ceiling, not a budget.** Measure this PR's number in Task 7 Step 4 and record
  it in the PR description so 2a-7 can see the trend. If the ceiling is ever threatened, the answer
  is fewer or faster harness tests — **never** dropping the live server, which is what carries
  2a-3 … 2a-6's event assertions and therefore the rows that port to Go.
- **The live server is already amortised per class, by Django itself.** Verified against the
  installed Django **6.0.8**: `LiveServerTestCase.setUpClass` calls `_start_server_thread()` and
  registers `addClassCleanup(cls._terminate_thread)`, so one server serves every test in a class and
  there is no `setUpClass`-level sharing left to add inside a class. Sharing *across* classes is not
  available without a custom runner, and is not worth it. The residual per-test cost is
  `TransactionTestCase._fixture_teardown`'s table flush, not the server; if the ceiling is
  threatened, the lever is `available_apps` on the harness base class to narrow that flush — measure
  before reaching for it.
- **No test sleeps for a fixed duration.** Every wait is a deadline poll:
  `harness.relay.wait_until(predicate, timeout, interval)` (Task 5), which returns as soon as the
  predicate holds and raises `AssertionError` naming the predicate when it does not.
- **Compress the clock through configuration, never by mocking `time`.** F8 lists what is
  compressible and what is not. `_monitor_health`'s `max_unhealthy_checks = 3` is a literal, so a
  dead-air test costs `3 × health_check_interval`; with `health_check_interval` patched to 0.2 s
  that is 0.6 s, not 15 s.
- **One `ProxyServer` per process, never torn down.** `ProxyServer.get_instance()`
  (`server.py:53-76`) is a process-wide singleton whose cleanup thread (`server.py:2192`) and event
  listener (`server.py:467`) are `while True` loops with **no stop flag** — they cannot be stopped
  and must not be created per test. Tests isolate by **unique channel UUID** plus per-test cleanup
  of that channel's Redis keys, not by rebuilding the server. Task 5's base class enforces this.

---

## File structure

Create:

| Path | Responsibility |
|---|---|
| `scripts/coverage_live_path.sh` | The Gate 2 command: run one label, or all three, under coverage; combine; report; refuse a foreign shape. |
| `scripts/coverage_live_path.coveragerc` | The measurement shape, self-contained (F2). The only place the ten `--include` patterns are written. |
| `apps/proxy/live_proxy/tests/harness/__init__.py` | Package marker; re-exports the public names. |
| `apps/proxy/live_proxy/tests/harness/asset.py` | Synthetic MPEG-TS asset + TS-shape assertions + the real-ffmpeg asset builder (Task 6). |
| `apps/proxy/live_proxy/tests/harness/faults.py` | The ported fault vocabulary and its store. |
| `apps/proxy/live_proxy/tests/harness/upstream.py` | `FakeUpstream` — threading HTTP server applying the faults. |
| `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/{normal,slow-trickle,truncation}.stderr` | Verbatim real-ffmpeg stderr captures. **Never hand-edited.** |
| `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md` | How the corpus was captured and how to regenerate it. |
| `apps/proxy/live_proxy/tests/harness/ffmpeg_stderr.py` | Loading and splitting the corpus; the `SYNTHETIC` register of declared exceptions. |
| `scripts/capture_ffmpeg_stderr.py` | Regenerates the corpus from a real ffmpeg. Not imported by any test. |
| `apps/proxy/live_proxy/tests/harness/standin.py` | The stand-in program's body. **Imports nothing from this repository** — it runs as a separate process. |
| `apps/proxy/live_proxy/tests/harness/process.py` | Installs `standin.py` as `ffmpeg` in a temp dir and puts it first on `PATH`; builds the matching `StreamProfile`. |
| `apps/proxy/live_proxy/tests/harness/relay.py` | `RelayHarnessTestCase` — bring-up, fixtures, deadline polling, per-channel teardown. |
| `apps/proxy/live_proxy/tests/harness/README.md` | What the harness is, the stated rule, how to add a test, what it deliberately does not do. |
| `apps/proxy/live_proxy/tests/test_harness_upstream.py` | Tests for `asset.py`, `faults.py`, `upstream.py`. |
| `apps/proxy/live_proxy/tests/test_harness_standin.py` | Tests that the stand-in spawns through the **production** `posix_spawn_proc` and behaves. |
| `apps/proxy/live_proxy/tests/test_harness_smoke.py` | The PR's named deliverable: an end-to-end tune over real HTTP producing real TS bytes from a real child process. |

Modify:

| Path | Change |
|---|---|
| `CLAUDE.md` | § Testing: "No backend unit test spawns a subprocess" becomes false with this PR. Correct it in the same PR, per the project's standing convention. |

Not touched, deliberately: `docs/relay-parity-matrix.md`, `e2e/**`, `e2e/COVERAGE.md` (no
Playwright test is added), `metrics/curated/**` (this PR closes no ledger issue, adds no
`test.fail()` pin, merges no goal and ticks no Done log), `.github/workflows/**`, `pyproject.toml`,
`uv.lock`, `.coveragerc` (the existing metrics rcfile stays exactly as it is).

---

## Interfaces at a glance

The names later tasks depend on, defined once here so a task's implementer can see them without
reading their neighbours' tasks.

```python
# harness/asset.py
TS_PACKET_SIZE: int = 188
TS_SYNC_BYTE: int = 0x47
def synthetic_ts(packets: int = 512, pid: int = 0x100) -> bytes: ...
def assert_ts_aligned(data: bytes) -> None: ...          # raises AssertionError
def build_real_ts_asset(seconds: float = 2.0) -> bytes: ...   # Task 6; needs real ffmpeg
def require_real_ffmpeg() -> str: ...                     # Task 6; returns the ffmpeg path or raises SkipTest

# harness/faults.py
PORTED_FAULTS: tuple[str, ...]
NOT_PORTED: dict[str, str]
class FaultStore:
    def arm(self, fault: str, **config) -> None: ...
    def clear(self, fault: str) -> None: ...
    def is_active(self, fault: str) -> bool: ...
    def config_of(self, fault: str) -> dict: ...
    def clear_all(self) -> None: ...

# harness/upstream.py
class FakeUpstream:
    url: str                 # e.g. "http://127.0.0.1:54321/live.ts"
    faults: FaultStore
    request_count: int
    def __init__(self, payload: bytes | None = None, rate: float | None = None) -> None: ...
    def start(self) -> "FakeUpstream": ...
    def stop(self) -> None: ...
    def __enter__(self) -> "FakeUpstream": ...
    def __exit__(self, *exc) -> None: ...

# harness/ffmpeg_stderr.py
CORPUS_NAMES: tuple[str, ...]                 # ("normal", "slow-trickle", "truncation")
SYNTHETIC: dict[str, tuple[str, str]]         # declared hand-written exceptions, with reasons
def path(name: str) -> str: ...
def load(name: str) -> bytes: ...
def split(name: str) -> tuple[bytes, list[bytes]]: ...      # (preamble, progress records)
def progress_lines(name: str) -> list[str]: ...

# harness/process.py
class StandInBin:
    path: str                # the temp directory placed first on PATH
    def __init__(self, *, stderr_corpus: str | None = "normal", stderr_interval: float = 0.05,
                 stderr_loop: bool = False, exit_after_bytes: int | None = None,
                 exit_code: int = 0, dead_air_after_bytes: int | None = None) -> None: ...
    def __enter__(self) -> "StandInBin": ...
    def __exit__(self, *exc) -> None: ...
def stand_in_stream_profile(name: str) -> "core.models.StreamProfile": ...

# harness/relay.py
def wait_until(predicate, *, timeout: float = 10.0, interval: float = 0.05, what: str = "") -> None: ...
class RelayHarnessTestCase(django.test.LiveServerTestCase):
    upstream: FakeUpstream
    def make_channel(self, *, upstream_url: str, profile) -> "apps.channels.models.Channel": ...
    def tuned(self, channel, *, timeout: float = 20.0):    # context manager -> _TunedStream
        ...
    def tune(self, channel, *, read_bytes: int = 3760, timeout: float = 20.0) -> bytes: ...
    def stop_channel(self, channel) -> None: ...
    def spawned_pid(self, channel) -> int: ...
    @staticmethod
    def process_is_alive(pid: int) -> bool: ...

class _TunedStream:          # what `tuned()` yields
    def read(self, count: int) -> bytes: ...   # exactly `count` bytes, or AssertionError
```

**`tuned()` is the primary interface and `tune()` the convenience wrapper, not the other way round.**
A relay test almost always has to observe *while the stream is open*: `channel_shutdown_delay`
defaults to 0 (`apps/proxy/config.py:54`), so the channel can begin tearing down as soon as the last
client disconnects, and anything asserted after the response is closed is racing that teardown.

---

## Task 1: `scripts/coverage_live_path.sh` and its rcfile

**Files:**
- Create: `scripts/coverage_live_path.sh` (mode 755)
- Create: `scripts/coverage_live_path.coveragerc`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: the command `scripts/coverage_live_path.sh` in three forms —
  `--label <django-label>` (measure one label, leave a parallel data file),
  `--report` (combine + report + print the percentage),
  no arguments (all three labels then report). Environment overrides:
  `COVERAGE_LIVE_PATH_DATA_DIR` (default `/tmp/dispatcharr-coverage-live-path`).
  2a-3 … 2a-6 quote the percentage this prints; 2a-7 adds a floor file beside it.

- [ ] **Step 1: Write the failing check**

There is nothing to unit-test in a shell script, so the test is the script's own behaviour. Write
this first, as `/tmp/2a2-check-task1.sh` (a scratch file, **not** committed):

```bash
#!/usr/bin/env bash
# Task 1 acceptance. Run inside the test container from /repo.
set -uo pipefail
fail() { echo "FAIL: $*"; exit 1; }

# 1. --report with no data must refuse, not print a number.
rm -rf /tmp/dispatcharr-coverage-live-path
out="$(scripts/coverage_live_path.sh --report 2>&1)"; rc=$?
[ "$rc" -ne 0 ] || fail "--report with no data exited 0"
grep -q "no coverage data" <<<"$out" || fail "--report gave no shape explanation: $out"

# 2. A data file with no shape stamp must be refused.
mkdir -p /tmp/dispatcharr-coverage-live-path
touch /tmp/dispatcharr-coverage-live-path/.coverage.foreign.1.2
out="$(scripts/coverage_live_path.sh --report 2>&1)"; rc=$?
[ "$rc" -ne 0 ] || fail "--report accepted an unstamped data file"
grep -q "measurement shape" <<<"$out" || fail "--report did not name the shape rule: $out"
rm -rf /tmp/dispatcharr-coverage-live-path

# 3. The full run reproduces the spec.
out="$(scripts/coverage_live_path.sh 2>&1)" || fail "full run exited non-zero: $out"
grep -qE "statements +7978" <<<"$out" || fail "denominator is not 7978: $out"
grep -qE "missing +3977" <<<"$out" || fail "missing is not 3977: $out"
grep -qE "coverage +50\.1[0-9]%" <<<"$out" || fail "percentage is not 50.1x%: $out"
echo "PASS"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker exec -w /repo dispatcharr-testrunner bash /tmp/2a2-check-task1.sh
```

Expected: `bash: scripts/coverage_live_path.sh: No such file or directory` and a non-zero exit.

- [ ] **Step 3: Write the rcfile**

`scripts/coverage_live_path.coveragerc`:

```ini
# Gate 2's measurement shape (Phase 2 spec, § Stage 2a > Gate 2). Self-contained
# on purpose: run from the repository root, coverage would otherwise pick up
# ./.coveragerc, whose `source = apps, core, dispatcharr` makes coverage ignore
# any --include with a CoverageWarning and measure the whole tree.
#
# Why `source` and not `include`: `source` triggers coverage's unexecuted-file
# walk, so a module no test imports is reported at 0% instead of vanishing from
# the denominator. Measured at a948cd8a: with `include` and no `source` the
# denominator is 7,877 rather than 7,978 -- the missing 101 statements are
# apps/proxy/live_proxy/input/http_streamer.py, which nothing imports. A
# denominator that shrinks when a file goes completely untested is the wrong
# shape for a ratchet.
[run]
source = apps/proxy
omit =
    */tests/*
parallel = True
data_file = ${COVERAGE_LIVE_PATH_DATA_DIR}/.coverage

# The ten Phase 1 boundary modules plus the relay, and nothing else: vod_proxy
# and the dead hls_proxy stay out, matching D1's scope line.
[report]
include =
    apps/proxy/live_proxy/*
    apps/proxy/authorize.py
    apps/proxy/authorize_views.py
    apps/proxy/control_plane.py
    apps/proxy/next_source.py
    apps/proxy/relay_client.py
    apps/proxy/relay_serializers.py
    apps/proxy/relay_views.py
    apps/proxy/permissions.py
    apps/proxy/internal_auth.py
    apps/proxy/internal_base_url.py
omit =
    */tests/*
skip_empty = True
```

Note: coverage expands `${VAR}` in config values, so `COVERAGE_LIVE_PATH_DATA_DIR` must be exported
by the script before any `coverage` call. The script does that unconditionally.

- [ ] **Step 4: Write the script**

`scripts/coverage_live_path.sh`:

```bash
#!/usr/bin/env bash
# Gate 2's measurement (Phase 2 spec, § Stage 2a > Gate 2): statement coverage
# over apps/proxy/live_proxy/** plus the ten Phase 1 boundary modules.
#
#   scripts/coverage_live_path.sh                  run all three labels, then report
#   scripts/coverage_live_path.sh --label <label>  run one label, leave its data file
#   scripts/coverage_live_path.sh --report         combine and report what is there
#
# Postgres and Redis must already be up. In CI that means running through
# scripts/ci_bootstrap_backend.sh with CI_BACKEND_RUNNER; locally it means the
# hook container (.claude/hooks/start-test-container.sh).
#
# THE MEASUREMENT SHAPE IS PART OF THE NUMBER, and this script enforces it.
# One process per test label is what backend-tests.yml runs. A single process
# running the same labels reports about 68 FEWER missed statements: the relay's
# daemon threads (server.py's cleanup loop and event listener, ClientManager's
# heartbeat) keep looping while unrelated tests run, and coverage credits lines
# no test asserts. A floor computed from that shape could never be met by the
# per-label pipeline meant to enforce it, so this script refuses to report over
# any data file it did not stamp itself -- and 2a-7's floor comparison hangs off
# the same check, so a floor can never be written or compared against a foreign
# shape either. Within this shape the measurement is exactly reproducible: the
# spec's +/-70-statement thread-timing band applies BETWEEN shapes, not between
# runs of this one, so this script has no tolerance and needs none.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The three labels whose tests reach the modules in the denominator. Hard-coded
# rather than derived: the spec names exactly these, and a 16-label control run
# at a948cd8a moved live_proxy by zero statements.
LABELS=(apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests)

export COVERAGE_LIVE_PATH_DATA_DIR="${COVERAGE_LIVE_PATH_DATA_DIR:-/tmp/dispatcharr-coverage-live-path}"
RC="$REPO_ROOT/scripts/coverage_live_path.coveragerc"
SHAPE_DIR="$COVERAGE_LIVE_PATH_DATA_DIR/shape"
# Bumped whenever the rcfile's denominator changes, so a stale data directory
# from before the change is refused instead of silently combined.
SHAPE_ID="per-label/v1"

run_label() {
  local label="$1"
  mkdir -p "$SHAPE_DIR"
  redis-cli -p "${REDIS_PORT:-6379}" flushall >/dev/null 2>&1 || true
  python -m coverage run --rcfile="$RC" manage.py test --keepdb "$label" -v1
  local rc=$?
  # Stamp AFTER the run: a label that died before coverage wrote its data file
  # must not leave a stamp claiming data that is not there.
  echo "$SHAPE_ID $label" > "$SHAPE_DIR/$(printf '%s' "$label" | tr '.' '_').shape"
  return $rc
}

report() {
  shopt -s nullglob
  local data=("$COVERAGE_LIVE_PATH_DATA_DIR"/.coverage.*)
  local stamps=("$SHAPE_DIR"/*.shape)
  shopt -u nullglob

  if [ "${#data[@]}" -eq 0 ]; then
    echo "coverage_live_path: no coverage data in $COVERAGE_LIVE_PATH_DATA_DIR" >&2
    echo "coverage_live_path: run this script with no arguments, or once per label with --label." >&2
    return 1
  fi
  if [ "${#stamps[@]}" -ne "${#data[@]}" ]; then
    echo "coverage_live_path: refusing to report -- ${#data[@]} data file(s) but ${#stamps[@]} shape stamp(s)." >&2
    echo "coverage_live_path: this script only reports over data it produced itself; see the measurement shape note at the top of this file." >&2
    return 1
  fi
  local stamp
  for stamp in "${stamps[@]}"; do
    if ! grep -q "^$SHAPE_ID " "$stamp"; then
      echo "coverage_live_path: refusing to report -- $stamp is not measurement shape '$SHAPE_ID'." >&2
      return 1
    fi
  done

  python -m coverage combine --rcfile="$RC" >/dev/null || return 1
  python -m coverage report --rcfile="$RC" || return 1
  python -m coverage json --rcfile="$RC" -o "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" >/dev/null || return 1
  python - "$COVERAGE_LIVE_PATH_DATA_DIR/live-path.json" <<'PY'
import json, sys
totals = json.load(open(sys.argv[1]))["totals"]
print(
    f'coverage_live_path: statements {totals["num_statements"]}  '
    f'missing {totals["missing_lines"]}  '
    f'coverage {totals["percent_covered"]:.2f}%'
)
PY
}

case "${1:-}" in
  --report)
    report; exit $?
    ;;
  --label)
    [ $# -eq 2 ] || { echo "usage: $0 --label <django-test-label>" >&2; exit 2; }
    run_label "$2"; exit $?
    ;;
  "")
    rm -rf "$COVERAGE_LIVE_PATH_DATA_DIR"
    mkdir -p "$SHAPE_DIR"
    failed=()
    for label in "${LABELS[@]}"; do
      run_label "$label" || failed+=("$label")
    done
    report; rc=$?
    if [ "${#failed[@]}" -gt 0 ]; then
      echo "coverage_live_path: label(s) failed under coverage: ${failed[*]}" >&2
      exit 1
    fi
    exit $rc
    ;;
  *)
    echo "usage: $0 [--label <django-test-label> | --report]" >&2; exit 2
    ;;
esac
```

- [ ] **Step 5: Make it executable and run the acceptance check**

```bash
chmod +x scripts/coverage_live_path.sh
docker exec -w /repo dispatcharr-testrunner bash /tmp/2a2-check-task1.sh
```

Expected: `PASS`, and the report block ending with

```
coverage_live_path: statements 7978  missing 3977  coverage 50.15%
```

If the denominator is 7,877 the rcfile lost its `source` line (F2). If it is far larger, the
`[report] omit` lost `*/tests/*`. If the run prints `CoverageWarning: --include is ignored`, the
rcfile is not being passed and `./.coveragerc` won its place — check `--rcfile="$RC"` on every
`coverage` call.

- [ ] **Step 6: Commit**

Write the message with the Write tool to `/tmp/2a2-msg-1.txt`, then in **separate** Bash calls:

```bash
git add scripts/coverage_live_path.sh scripts/coverage_live_path.coveragerc
```

```bash
git commit -F /tmp/2a2-msg-1.txt
```

Message body: `test(phase2): scripts/coverage_live_path.sh — the Gate 2 measurement, per-label` plus
a paragraph recording F1 and F2, plus the two trailer lines from § Global Constraints.

---

## Task 2: The synthetic TS asset and the fault vocabulary

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/__init__.py`
- Create: `apps/proxy/live_proxy/tests/harness/asset.py`
- Create: `apps/proxy/live_proxy/tests/harness/faults.py`
- Create: `apps/proxy/live_proxy/tests/test_harness_upstream.py` (the asset/fault half; Task 3 adds
  the server half to the same file)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `TS_PACKET_SIZE`, `TS_SYNC_BYTE`, `synthetic_ts(packets, pid) -> bytes`,
  `assert_ts_aligned(data) -> None`; `PORTED_FAULTS`, `NOT_PORTED`, `FaultStore` with
  `arm/clear/is_active/config_of/clear_all`. Task 3's `FakeUpstream` owns a `FaultStore` and serves
  `synthetic_ts(...)`; Task 5's smoke test calls `assert_ts_aligned`.

**The fault vocabulary, and what is deliberately left behind.** `e2e-upstream/src/faults.ts:4-16`
declares twelve faults. Eight are live-TS faults and port; four belong to surfaces D1 leaves in
Python (VOD, catch-up, the XC listing API) and are recorded as not ported rather than silently
dropped, so the Go author copying this vocabulary in 2c sees the whole twelve and why four are
missing.

| Fault | Ported | Shape at the upstream | Serves |
|---|---|---|---|
| `dead-air` | yes | headers sent, then nothing; socket stays open | matrix row 2 |
| `slow-trickle` | yes | pace output at `rate` × the nominal byte rate | rows 1, 4 |
| `disconnect` | yes | close after `after_bytes`; `clean` chooses shutdown vs. abrupt | mid-stream truncation |
| `not-found` | yes | 404 before any body (`e2e-upstream/src/server.ts:291-293`) | row 3 |
| `auth-failure` | yes | 401 (`server.ts:298-300`) | row 3 |
| `connection-limit` | yes | 429 (`server.ts:357-359`) | row 3 |
| `redirect-chain` | yes | `depth` × 302 then the real body (`server.ts:323-338`) | URL resolution |
| `non-ts-bytes` | yes | 200 with an HTML error page (`server.ts:343`) | row 9 (realignment) |
| `xc-auth-envelope` | **no** | XC `player_api.php` envelope — not a live-TS surface | — |
| `no-tv-archive` | **no** | XC catch-up advertisement — Phase 3's scope | — |
| `catchup-layout-404` | **no** | catch-up URL layout — Phase 3's scope | — |
| `range-unsupported` | **no** | VOD `Range` handling — D1 leaves VOD in Python | — |

Eight ported, four not; 8 + 4 = 12, matching `FAULT_NAMES`.

- [ ] **Step 1: Write the failing test**

`apps/proxy/live_proxy/tests/test_harness_upstream.py`:

```python
"""Tests for the 2a subprocess harness's fake upstream, asset and faults."""

from django.test import SimpleTestCase

from .harness.asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
from .harness.faults import NOT_PORTED, PORTED_FAULTS, FaultStore


class SyntheticAssetTests(SimpleTestCase):
    def test_asset_is_a_whole_number_of_packets(self):
        data = synthetic_ts(packets=7)
        self.assertEqual(len(data), 7 * TS_PACKET_SIZE)

    def test_every_packet_starts_with_the_sync_byte(self):
        data = synthetic_ts(packets=16)
        for offset in range(0, len(data), TS_PACKET_SIZE):
            self.assertEqual(data[offset], TS_SYNC_BYTE, f"packet at {offset}")

    def test_continuity_counter_increments_and_wraps_at_16(self):
        data = synthetic_ts(packets=20)
        counters = [data[i + 3] & 0x0F for i in range(0, len(data), TS_PACKET_SIZE)]
        self.assertEqual(counters[:17], [i % 16 for i in range(17)])

    def test_pid_is_carried_in_the_low_thirteen_bits(self):
        data = synthetic_ts(packets=2, pid=0x1FF)
        pid = ((data[1] & 0x1F) << 8) | data[2]
        self.assertEqual(pid, 0x1FF)

    def test_assert_ts_aligned_accepts_a_clean_stream(self):
        assert_ts_aligned(synthetic_ts(packets=4))

    def test_assert_ts_aligned_rejects_a_shifted_stream(self):
        with self.assertRaises(AssertionError):
            assert_ts_aligned(b"\x00" + synthetic_ts(packets=4))


class FaultVocabularyTests(SimpleTestCase):
    def test_the_vocabulary_covers_all_twelve_upstream_faults(self):
        self.assertEqual(len(PORTED_FAULTS), 8)
        self.assertEqual(len(NOT_PORTED), 4)
        self.assertEqual(set(PORTED_FAULTS) & set(NOT_PORTED), set())

    def test_every_not_ported_fault_carries_a_reason(self):
        for name, reason in NOT_PORTED.items():
            self.assertTrue(reason.strip(), f"{name} has no reason")

    def test_arming_an_unknown_fault_is_an_error(self):
        with self.assertRaises(ValueError):
            FaultStore().arm("no-such-fault")

    def test_arming_a_not_ported_fault_names_the_reason(self):
        with self.assertRaises(ValueError) as caught:
            FaultStore().arm("range-unsupported")
        self.assertIn("VOD", str(caught.exception))

    def test_arm_then_clear_round_trips(self):
        store = FaultStore()
        self.assertFalse(store.is_active("dead-air"))
        store.arm("dead-air")
        self.assertTrue(store.is_active("dead-air"))
        store.clear("dead-air")
        self.assertFalse(store.is_active("dead-air"))

    def test_config_of_returns_the_armed_configuration(self):
        store = FaultStore()
        store.arm("slow-trickle", rate=0.25)
        self.assertEqual(store.config_of("slow-trickle")["rate"], 0.25)

    def test_config_of_an_unarmed_fault_is_empty(self):
        self.assertEqual(FaultStore().config_of("slow-trickle"), {})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker exec -w /repo dispatcharr-testrunner bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH DISPATCHARR_ENV=aio POSTGRES_HOST=/var/run/postgresql \
     POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432 \
     REDIS_HOST=localhost REDIS_PORT=6379 DJANGO_SECRET_KEY=ci-test-secret-key \
     DISPATCHARR_LOG_LEVEL=WARNING; \
   python manage.py test --keepdb apps.proxy.live_proxy.tests.test_harness_upstream -v2'
```

Expected: `ModuleNotFoundError: No module named 'apps.proxy.live_proxy.tests.harness'`.

*(Keep that environment prefix to hand — every later "run the tests" step uses it. It is written out
once more in § Verification command at the end and not repeated in every step.)*

- [ ] **Step 3: Write `harness/__init__.py`**

```python
"""The stage-2a subprocess harness.

Every spawn in this harness is a real child process created by the relay's own
unmodified os.posix_spawn call sites. What that child *runs* is chosen through
two production mechanisms -- a StreamProfile row's `command`, and PATH -- so the
harness needs no seam, no patch and no production-code change. See README.md.
"""

from .asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
from .faults import NOT_PORTED, PORTED_FAULTS, FaultStore

__all__ = [
    "TS_PACKET_SIZE",
    "TS_SYNC_BYTE",
    "assert_ts_aligned",
    "synthetic_ts",
    "NOT_PORTED",
    "PORTED_FAULTS",
    "FaultStore",
]
```

Note the deliberate omission: `upstream`, `process` and `relay` are **not** re-exported here.
`relay.py` imports Django's test machinery and `core.models`; re-exporting it from the package
`__init__` would make `from .harness.asset import …` in a `SimpleTestCase` drag Django's ORM in.
Task 3, 5 and 6 import their modules by full path.

- [ ] **Step 4: Write `harness/asset.py`** (the Task 6 additions come later; write only these now)

```python
"""A synthetic MPEG-TS asset, and the TS-shape assertions tests make about it.

Synthetic rather than ffmpeg-produced on purpose: nothing on the live path
decodes video. input/buffer.py realigns on the 0x47 sync byte at a 188-byte
stride and the ring buffer carries whatever it is given, so a structurally
valid transport stream is exactly as useful here as a real encode, costs no
ffmpeg, and is byte-for-byte deterministic. Where a REAL remuxer's output is
required -- the fMP4 path, which parses moof/moov boxes -- use
build_real_ts_asset() instead; that is 2a-6's territory.
"""

TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47


def synthetic_ts(packets: int = 512, pid: int = 0x100) -> bytes:
    """`packets` transport-stream packets on `pid`, with a real continuity counter.

    Each packet is: 0x47, then the 13-bit PID split across two bytes with the
    payload-unit-start flag clear, then 0x10 | (counter % 16) -- adaptation
    field control 01 (payload only) in the high nibble, the continuity counter
    in the low one -- then 184 bytes of a repeating, position-derived pattern so
    a test can tell one packet from another.
    """
    if packets < 1:
        raise ValueError("packets must be >= 1")
    if not 0 <= pid <= 0x1FFF:
        raise ValueError("pid must fit in 13 bits")

    out = bytearray()
    for i in range(packets):
        out.append(TS_SYNC_BYTE)
        out.append((pid >> 8) & 0x1F)
        out.append(pid & 0xFF)
        out.append(0x10 | (i % 16))
        out.extend(bytes((i + j) % 256 for j in range(TS_PACKET_SIZE - 4)))
    return bytes(out)


def assert_ts_aligned(data: bytes) -> None:
    """Fail unless `data` is a whole number of packets, each starting with 0x47."""
    if not data:
        raise AssertionError("no bytes at all")
    if len(data) % TS_PACKET_SIZE:
        raise AssertionError(
            f"{len(data)} bytes is not a whole number of {TS_PACKET_SIZE}-byte packets"
        )
    for offset in range(0, len(data), TS_PACKET_SIZE):
        if data[offset] != TS_SYNC_BYTE:
            raise AssertionError(
                f"byte {offset} is {data[offset]:#04x}, not the sync byte {TS_SYNC_BYTE:#04x}"
            )
```

- [ ] **Step 5: Write `harness/faults.py`**

```python
"""The fault vocabulary, ported from e2e-upstream/src/faults.ts.

e2e-upstream declares twelve faults (faults.ts:4-16). Eight are live-TS faults
and are reproduced here; four belong to surfaces Phase 2's D1 leaves in Python
(VOD, catch-up, the XC listing API) and are recorded in NOT_PORTED rather than
dropped, so 2c's Go fixtures can copy the whole vocabulary and see which four
were left behind and why.

Deliberately NOT a port of the TypeScript implementation: there is no scenario
id and no per-channel scope here. One FakeUpstream serves one channel in a
backend test, so a fault is either armed on that server or it is not.
"""

DEAD_AIR = "dead-air"
SLOW_TRICKLE = "slow-trickle"
DISCONNECT = "disconnect"
NOT_FOUND = "not-found"
AUTH_FAILURE = "auth-failure"
CONNECTION_LIMIT = "connection-limit"
REDIRECT_CHAIN = "redirect-chain"
NON_TS_BYTES = "non-ts-bytes"

PORTED_FAULTS: tuple[str, ...] = (
    DEAD_AIR,
    SLOW_TRICKLE,
    DISCONNECT,
    NOT_FOUND,
    AUTH_FAILURE,
    CONNECTION_LIMIT,
    REDIRECT_CHAIN,
    NON_TS_BYTES,
)

NOT_PORTED: dict[str, str] = {
    "xc-auth-envelope": (
        "shapes the XC player_api.php envelope, a listing surface the Go relay "
        "never serves (D1)"
    ),
    "no-tv-archive": "XC catch-up advertisement; catch-up stays Python (D1)",
    "catchup-layout-404": "catch-up URL layout; catch-up stays Python (D1)",
    "range-unsupported": "VOD Range handling; VOD stays Python (D1)",
}

# Defaults chosen to match e2e-upstream's own (faults.ts:75 DEFAULT_REDIRECT_DEPTH,
# and DEFAULT_TRICKLE_RATE = 0.1) so a fault armed the same way behaves the same
# way in both suites.
_DEFAULTS: dict[str, dict] = {
    DEAD_AIR: {},
    SLOW_TRICKLE: {"rate": 0.1},
    DISCONNECT: {"clean": False, "after_bytes": 0},
    NOT_FOUND: {},
    AUTH_FAILURE: {},
    CONNECTION_LIMIT: {},
    REDIRECT_CHAIN: {"depth": 2},
    NON_TS_BYTES: {},
}


class FaultStore:
    """Which faults are armed on one FakeUpstream, and with what configuration."""

    def __init__(self) -> None:
        self._armed: dict[str, dict] = {}

    def arm(self, fault: str, **config) -> None:
        if fault in NOT_PORTED:
            raise ValueError(f"{fault!r} is not ported to the backend harness: {NOT_PORTED[fault]}")
        if fault not in _DEFAULTS:
            raise ValueError(f"unknown fault {fault!r}; expected one of {', '.join(PORTED_FAULTS)}")
        unknown = set(config) - set(_DEFAULTS[fault])
        if unknown:
            raise ValueError(f"{fault!r} takes no option(s): {', '.join(sorted(unknown))}")
        merged = dict(_DEFAULTS[fault])
        merged.update(config)
        self._armed[fault] = merged

    def clear(self, fault: str) -> None:
        self._armed.pop(fault, None)

    def clear_all(self) -> None:
        self._armed.clear()

    def is_active(self, fault: str) -> bool:
        return fault in self._armed

    def config_of(self, fault: str) -> dict:
        return dict(self._armed.get(fault, {}))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run the command from Step 2. Expected: 13 tests, `OK`.

- [ ] **Step 7: Run the whole package (the hook will do this on the edit; do it explicitly anyway)**

```bash
… python manage.py test --keepdb apps.proxy.live_proxy apps.channels -v1
```

Expected: `OK`, no new failures against the pre-existing baseline.

- [ ] **Step 8: Commit** (message to `/tmp/2a2-msg-2.txt`, `git add` and `git commit -F` in separate
      Bash calls, trailers included)

---

## Task 3: The in-process fake upstream

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/upstream.py`
- Modify: `apps/proxy/live_proxy/tests/test_harness_upstream.py` (append the server tests)

**Interfaces:**
- Consumes: `synthetic_ts`, `assert_ts_aligned`, `TS_PACKET_SIZE` from `harness.asset`;
  `FaultStore`, `PORTED_FAULTS` from `harness.faults` (Task 2).
- Produces: `FakeUpstream` with `url`, `faults`, `request_count`, `start()`, `stop()` and the
  context-manager protocol. Task 4's stand-in test fetches from it; Task 5's `RelayHarnessTestCase`
  owns one per test.

- [ ] **Step 1: Write the failing tests** — append to `test_harness_upstream.py`:

```python
import urllib.error
import urllib.request

from .harness.upstream import FakeUpstream


class FakeUpstreamTests(SimpleTestCase):
    def test_serves_ts_bytes(self):
        with FakeUpstream(payload=synthetic_ts(packets=32)) as up:
            with urllib.request.urlopen(up.url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "video/mp2t")
                body = response.read(32 * TS_PACKET_SIZE)
        assert_ts_aligned(body)

    def test_loops_the_payload_rather_than_ending(self):
        with FakeUpstream(payload=synthetic_ts(packets=4)) as up:
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read(4 * TS_PACKET_SIZE * 3)
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE * 3)
        assert_ts_aligned(body)

    def test_counts_requests(self):
        with FakeUpstream(payload=synthetic_ts(packets=2)) as up:
            self.assertEqual(up.request_count, 0)
            for _ in range(2):
                with urllib.request.urlopen(up.url, timeout=5) as response:
                    response.read(TS_PACKET_SIZE)
            self.assertEqual(up.request_count, 2)

    def test_not_found_fault_answers_404(self):
        with FakeUpstream() as up:
            up.faults.arm("not-found")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 404)

    def test_auth_failure_fault_answers_401(self):
        with FakeUpstream() as up:
            up.faults.arm("auth-failure")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 401)

    def test_connection_limit_fault_answers_429(self):
        with FakeUpstream() as up:
            up.faults.arm("connection-limit")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 429)

    def test_redirect_chain_fault_lands_on_the_stream(self):
        with FakeUpstream(payload=synthetic_ts(packets=2)) as up:
            up.faults.arm("redirect-chain", depth=3)
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read(2 * TS_PACKET_SIZE)
        assert_ts_aligned(body)
        # One request for each hop plus the final one that serves bytes.
        self.assertEqual(up.request_count, 4)

    def test_non_ts_bytes_fault_answers_200_with_html(self):
        with FakeUpstream() as up:
            up.faults.arm("non-ts-bytes")
            with urllib.request.urlopen(up.url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                body = response.read()
        self.assertNotEqual(body[:1], b"\x47")
        self.assertIn(b"<html", body.lower())

    def test_disconnect_fault_truncates_after_the_configured_bytes(self):
        with FakeUpstream(payload=synthetic_ts(packets=64)) as up:
            up.faults.arm("disconnect", after_bytes=4 * TS_PACKET_SIZE)
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read()
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE)

    def test_dead_air_fault_sends_headers_and_no_body(self):
        with FakeUpstream(payload=synthetic_ts(packets=8)) as up:
            up.faults.arm("dead-air")
            response = urllib.request.urlopen(up.url, timeout=5)
            try:
                self.assertEqual(response.status, 200)
                response.fp.raw._sock.settimeout(0.5)
                with self.assertRaises(OSError):
                    response.read(TS_PACKET_SIZE)
            finally:
                response.close()

    def test_every_ported_fault_can_be_armed_on_a_running_server(self):
        with FakeUpstream() as up:
            for fault in PORTED_FAULTS:
                up.faults.arm(fault)
                up.faults.clear(fault)
```

- [ ] **Step 2: Run to verify failure** — expected `ImportError: cannot import name 'FakeUpstream'`.

- [ ] **Step 3: Write `harness/upstream.py`**

```python
"""An in-process HTTP upstream for backend tests.

Not a reuse of the e2e-upstream Docker image on purpose: the backend test runner
is itself a container, and a sibling container per test is a poor trade for
something that has to start in milliseconds. This serves one looping TS payload
on one path, with the eight live-TS faults harness.faults ports.

Threading, not gevent: manage.py test does not monkey-patch (the patch is
applied only by dispatcharr/gevent_patch.py, imported from the uWSGI ini files),
so ThreadingHTTPServer's real OS threads are the right primitive and are the
same primitive the relay's own workers use under test.
"""

import http.server
import threading
import time

from .asset import TS_PACKET_SIZE, synthetic_ts
from .faults import FaultStore

_HTML_ERROR_PAGE = (
    b"<html><head><title>502 Bad Gateway</title></head>"
    b"<body><h1>502 Bad Gateway</h1></body></html>"
)

# What "rate 1.0" means, in bytes per second: 2 Mbit/s, the bitrate
# e2e-upstream/scripts/make-asset.sh builds its own asset at. slow-trickle's
# rate multiplies this.
NOMINAL_BYTE_RATE = 2_000_000 // 8

_WRITE_CHUNK = TS_PACKET_SIZE * 50  # 9,400 bytes


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Silence BaseHTTPRequestHandler's stderr access log; a test that wants to
    # know what was requested reads server.request_count.
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802 - the stdlib's name
        upstream = self.server.upstream
        faults = upstream.faults
        with upstream._lock:
            upstream.request_count += 1
            hop = upstream._redirect_hops

        if faults.is_active("not-found"):
            self._send_short(404, b'{"error": "fault: not-found"}', "application/json")
            return
        if faults.is_active("auth-failure"):
            self._send_short(401, b'{"error": "fault: auth-failure"}', "application/json")
            return
        if faults.is_active("connection-limit"):
            self._send_short(429, b'{"error": "fault: connection-limit"}', "application/json")
            return

        if faults.is_active("redirect-chain"):
            depth = faults.config_of("redirect-chain")["depth"]
            if hop < depth:
                with upstream._lock:
                    upstream._redirect_hops += 1
                self.send_response(302)
                self.send_header("Location", upstream.url)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Chain exhausted: this request serves the stream, and the next
            # connection starts a fresh chain.
            with upstream._lock:
                upstream._redirect_hops = 0

        if faults.is_active("non-ts-bytes"):
            self._send_short(200, _HTML_ERROR_PAGE, "text/html")
            return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Connection", "close")
        self.end_headers()

        if faults.is_active("dead-air"):
            # Headers sent, nothing else, socket held open -- exactly what a
            # provider that stops producing looks like from the relay's side.
            deadline = time.monotonic() + upstream.dead_air_hold_seconds
            while time.monotonic() < deadline and not upstream._stopping.is_set():
                time.sleep(0.05)
            return

        self._stream(upstream)

    def _send_short(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, upstream):
        payload = upstream.payload
        faults = upstream.faults

        rate = None
        if faults.is_active("slow-trickle"):
            rate = faults.config_of("slow-trickle")["rate"] * NOMINAL_BYTE_RATE
        elif upstream.rate is not None:
            rate = upstream.rate * NOMINAL_BYTE_RATE

        stop_after = None
        clean = True
        if faults.is_active("disconnect"):
            config = faults.config_of("disconnect")
            stop_after = config["after_bytes"]
            clean = config["clean"]

        sent = 0
        at = 0
        started = time.monotonic()
        try:
            while not upstream._stopping.is_set():
                if stop_after is not None and sent >= stop_after:
                    if not clean:
                        # Abrupt: drop the socket without a clean shutdown, so
                        # the reader sees a connection reset rather than EOF.
                        self.close_connection = True
                        try:
                            self.connection.close()
                        except OSError:
                            pass
                    return
                chunk = _WRITE_CHUNK
                if stop_after is not None:
                    chunk = min(chunk, stop_after - sent)
                piece = bytearray()
                while len(piece) < chunk:
                    take = min(chunk - len(piece), len(payload) - at)
                    piece += payload[at : at + take]
                    at = (at + take) % len(payload)
                self.wfile.write(bytes(piece))
                sent += len(piece)
                if rate is not None:
                    due = started + sent / rate
                    now = time.monotonic()
                    if due > now:
                        time.sleep(min(due - now, 0.25))
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The relay closed its side -- an ordinary end to a tune.
            return


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # A tune ending, or the `disconnect` fault firing, closes a socket
        # mid-response. socketserver's default handle_error prints a full
        # traceback to stderr for each one, which would bury every real test
        # failure in noise. Swallowed here deliberately: nothing about this
        # server's own errors is under test, and a test that cares asserts on
        # what the client received.
        pass


class FakeUpstream:
    """A looping TS upstream on 127.0.0.1, with injectable faults.

    `payload` defaults to 512 synthetic packets (~96 KB). `rate`, when set,
    paces every response at that multiple of NOMINAL_BYTE_RATE even with no
    slow-trickle fault armed -- the way a test asks for a steady, unhurried
    stream rather than one that fills the ring buffer as fast as the loopback
    allows.
    """

    dead_air_hold_seconds = 30.0

    def __init__(self, payload: bytes | None = None, rate: float | None = None) -> None:
        self.payload = payload if payload is not None else synthetic_ts(packets=512)
        if not self.payload:
            raise ValueError("payload must not be empty")
        self.rate = rate
        self.faults = FaultStore()
        self.request_count = 0
        self._redirect_hops = 0
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def start(self) -> "FakeUpstream":
        if self._server is not None:
            raise RuntimeError("already started")
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.upstream = self
        host, port = self._server.server_address[:2]
        self.url = f"http://{host}:{port}/live.ts"
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="fake-upstream", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "FakeUpstream":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
```

- [ ] **Step 4: Run the tests to verify they pass** — expected 24 tests in the module, `OK`.

Two predictable snags, with their resolutions:

- `test_dead_air_fault_sends_headers_and_no_body` reaches into `response.fp.raw._sock` to set a
  socket timeout, because `urllib` has no per-read timeout. If that attribute path does not exist on
  this Python build, replace the body with a raw `socket`/`http.client.HTTPConnection` that sets
  `settimeout(0.5)` on the connection before `getresponse().read(188)` and assert `socket.timeout`.
  **Do not** weaken the test to "the request did not raise" — that passes whether or not the fault
  works.
- `test_disconnect_fault_truncates_after_the_configured_bytes` uses `clean` defaulting to `False`,
  which closes the socket abruptly; `response.read()` may raise `http.client.IncompleteRead` or
  `ConnectionResetError` rather than returning short. If it does, catch it and assert on
  `exc.partial` (or on what was read before the reset) — the assertion is about the byte count, not
  about which exception delivers it.
- `test_redirect_chain_fault_lands_on_the_stream` redirects to the **same** URL three times.
  `urllib.request.HTTPRedirectHandler` counts repeat visits and raises `HTTPError` once a single
  `(url, method)` pair is visited more than `max_repeats` (4), so `depth=3` is inside the limit and
  `depth=5` would not be. If that limit turns out to bite anyway, use
  `requests.get(up.url, stream=True)` — `requests` allows 30 redirects by default and is already a
  dependency — rather than lowering `depth` below what the test is asserting.

- [ ] **Step 5: Run the whole package.** Expected `OK`.

- [ ] **Step 6: Commit** (message to `/tmp/2a2-msg-3.txt`; separate `git add` / `git commit -F`).

---

## Task 4: The process stand-in, its real-ffmpeg stderr corpus, and the production spawn path

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/normal.stderr`
- Create: `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/slow-trickle.stderr`
- Create: `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/truncation.stderr`
- Create: `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md`
- Create: `apps/proxy/live_proxy/tests/harness/ffmpeg_stderr.py`
- Create: `apps/proxy/live_proxy/tests/harness/standin.py`
- Create: `apps/proxy/live_proxy/tests/harness/process.py`
- Create: `scripts/capture_ffmpeg_stderr.py`
- Create: `apps/proxy/live_proxy/tests/test_harness_standin.py`

**Interfaces:**
- Consumes: `FakeUpstream` (Task 3), `TS_PACKET_SIZE`/`assert_ts_aligned` (Task 2),
  `require_real_ffmpeg`/`ffmpeg_env` (Task 6 — but only `scripts/capture_ffmpeg_stderr.py` uses
  them, and that script is not imported by any test, so Task 4 does not depend on Task 6; the
  script sets `LD_LIBRARY_PATH` itself, in six lines, and Task 6's helper is the reusable version
  of the same three checks).
- Produces: `CORPUS_NAMES`, `load(name) -> bytes`, `split(name) -> (preamble, records)`,
  `progress_lines(name) -> list[str]` and `SYNTHETIC` from `harness.ffmpeg_stderr`; `StandInBin`
  (context manager; attribute `path`; prepends itself to `os.environ["PATH"]` on enter and restores
  on exit) and `stand_in_stream_profile(name) -> StreamProfile` from `harness.process`. Task 5's
  `RelayHarnessTestCase` uses `StandInBin` and `stand_in_stream_profile`; 2a-4 uses
  `harness.ffmpeg_stderr` directly for the buffering-detector rows.

**Why the corpus exists, and why it is the load-bearing half of this task.** `CLAUDE.md` § Testing
names the gap this stage is closing as "ffmpeg lifecycle and stderr parsing run only against
hand-written strings there." A stand-in that replays *invented* `speed=` lines reproduces that gap
exactly: rows 1-6 would assert that `log_parsers.py` parses our own fiction. Real ffmpeg does run
once `LD_LIBRARY_PATH=/usr/local/lib` is set (F4), so the corpus is captured **once** from a real
ffmpeg against a real upstream, committed as a fixture, and replayed by the stand-in at whatever
cadence a test asks for. Realism comes from the capture; speed comes from the replay.

**The corpus was already captured while this plan was written**, so its content and its shape are
facts, not a hope. Reproduce it with `scripts/capture_ffmpeg_stderr.py` (Step 3) if ffmpeg ever
drifts; the numbers below are what ffmpeg 8.1.2 produced in `dispatcharr-testrunner` on 2026-09-10,
driving the **production** ffmpeg command (`core/migrations/0003_preload_stream_profiles.py:10`:
`ffmpeg -i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, no `-loglevel`, so default `info`)
against a looping 8-second lavfi asset served over HTTP at a controlled rate:

| Fixture | Capture | Size | Progress lines | What it carries |
|---|---|---|---|---|
| `normal.stderr` | upstream at 2.0× real time, 8 s | 4,450 B | 11 | banner, `Input #0, mpegts`, `Stream mapping:`, `Output #0, mpegts, to 'pipe:1'`, `Press [q] to stop`, then `speed=` decaying 11.5x → 2.84x |
| `slow-trickle.stderr` | upstream at 0.25× real time, 45 s | 13,278 B | 76 | the same preamble, then a cumulative `speed=` that starts at **10.7x**, first dips below 1.0 at line 36 (`speed=0.99x`, `elapsed=0:00:18.21`) and is **continuously below 1.0 from line 38 to the end** (39 lines, ending `speed=0.85x` at `elapsed=0:00:38.43`) |
| `truncation.stderr` | upstream at 2.0×, cut after 3 s of media | 2,618 B | 1 | `[http @ 0x…] Stream ends prematurely at 190068, should be 18446744073709551615`, `[in#0/mpegts @ 0x…] Error during demuxing: Input/output error`, and a final `Lsize=` line |

**`slow-trickle.stderr` is the single most valuable artefact in this PR**, because it is empirical
proof of parity-matrix row 4 — "`speed=` is a cumulative average since process start, taking ~55s to
arm." Against a genuinely 0.25×-real-time upstream, real ffmpeg needed **18 seconds of wall clock**
before the cumulative average first touched 1.0 and **20 seconds** before it stayed there. That is
the arming delay, measured, and it is exactly why 2a-4 cannot drive row 1 or row 4 with a live
ffmpeg inside a test budget: it has to replay these 76 records at its own cadence.

**Details of the real format that a hand-written line would have got wrong**, all present in the
corpus and all worth knowing before writing an assertion:

- ffmpeg 8.1.2 appends an **`elapsed=0:00:00.50`** field after `speed=`, which older documented
  examples (including the comment at `input/manager.py:1062`) do not show.
- The **final** progress line uses `Lsize=`, not `size=`.
- The speed field is **space-padded** when short: `speed= 1.1x`, with a space. The production regex
  `re.search(r'speed=\s*([0-9.]+)x?', …)` (`input/manager.py:1065`) has the `\s*` and handles it;
  two of the 76 lines in `slow-trickle.stderr` are of this form, so the corpus exercises it.
- Records are separated by **`\r`, not `\n`** — ffmpeg rewrites one status line in place. Anything
  splitting the corpus on `\n` alone gets one enormous line.
- **A real ffmpeg emits `speed=` in scientific notation.** `truncation.stderr`'s only progress line
  is `speed=1.82e+03x`. See § Findings, item 5: the production regex parses that as **1.82**.

**How the stand-in is reached.** `StandInBin.__enter__` writes into a fresh `tempfile.mkdtemp()`:
`standin.py`, copied byte-for-byte from `apps/proxy/live_proxy/tests/harness/standin.py`; the
selected corpus fixture, also copied; and an executable named **`ffmpeg`** whose whole body is a
shebang plus a few lines that `runpy.run_path` the copy. It then prepends the directory to
`os.environ["PATH"]`. Copying rather than pointing at the in-tree files matters twice: the
repository is bind-mounted **read-only** in the hook container, so the in-tree file cannot be given
an exec bit at test time; and the temp copy keeps the child from importing anything from this
repository, which is what makes it a genuine external program rather than a Python object wearing a
costume.

- [ ] **Step 1: Write `scripts/capture_ffmpeg_stderr.py` and capture the three fixtures**

The script is committed so the corpus can be regenerated when ffmpeg drifts. It is not imported by
any test and is not part of the harness package.

```python
#!/usr/bin/env python3
"""Capture a real ffmpeg stderr corpus for the stage-2a subprocess harness.

Run inside the backend test container:

    docker exec -w /repo dispatcharr-testrunner bash -lc \
      'export PATH=/dispatcharrpy/bin:$PATH; python scripts/capture_ffmpeg_stderr.py \
         apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr'

Drives the PRODUCTION ffmpeg command -- core/migrations/0003_preload_stream_profiles.py's
`ffmpeg -i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, no -loglevel, so the
default `info` -- against a looping lavfi asset served over HTTP at a controlled
rate, and writes each run's raw stderr bytes verbatim (\\r separators included).

LD_LIBRARY_PATH is set for every child: the image carries two librist and the
loader picks the wrong one without it, so an unqualified ffmpeg dies with
`undefined symbol: rist_peer_config_defaults_set_versioned`. docker/entrypoint.sh
sets this in production; no test context runs that entrypoint.
"""

import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time

FFMPEG_ENV = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/lib"}
ASSET_SECONDS = 8

# name, seconds to run, upstream rate (x real time), truncate after N seconds of media
RUNS = [
    ("normal", 8, 2.0, None),
    ("slow-trickle", 45, 0.25, None),
    ("truncation", 10, 2.0, 3.0),
]


def build_asset():
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={ASSET_SECONDS}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={ASSET_SECONDS}",
         "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "400k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "pipe:1"],
        capture_output=True, env=FFMPEG_ENV, timeout=120,
    )
    if done.returncode != 0:
        raise SystemExit("ffmpeg could not build the asset: "
                         + done.stderr.decode(errors="replace")[:400])
    return done.stdout


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    asset = build_asset()
    byte_rate = len(asset) / ASSET_SECONDS
    print(f"asset: {len(asset)} bytes, {len(asset) // 188} packets, {int(byte_rate)} B/s")

    mode = {"rate": 1.0, "truncate_at": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Connection", "close")
            self.end_headers()
            rate = mode["rate"] * byte_rate
            truncate_at = mode["truncate_at"]
            sent = at = 0
            started = time.monotonic()
            try:
                while True:
                    if truncate_at is not None and sent >= truncate_at:
                        self.connection.close()
                        return
                    want = 9400
                    if truncate_at is not None:
                        want = min(want, truncate_at - sent)
                    piece = bytearray()
                    while len(piece) < want:
                        take = min(want - len(piece), len(asset) - at)
                        piece += asset[at:at + take]
                        at = (at + take) % len(asset)
                    self.wfile.write(bytes(piece))
                    sent += len(piece)
                    due = started + sent / rate
                    now = time.monotonic()
                    if due > now:
                        time.sleep(min(due - now, 0.2))
            except OSError:
                return

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/live.ts"

    for name, seconds, rate, truncate_seconds in RUNS:
        mode["rate"] = rate
        mode["truncate_at"] = None if truncate_seconds is None else int(byte_rate * truncate_seconds)
        child = subprocess.Popen(
            ["ffmpeg", "-i", url, "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=FFMPEG_ENV,
        )
        chunks = []

        def drain(stream=child.stderr, sink=chunks):
            while True:
                block = stream.read(4096)
                if not block:
                    break
                sink.append(block)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        time.sleep(seconds)
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        reader.join(timeout=5)

        data = b"".join(chunks)
        path = os.path.join(out_dir, f"{name}.stderr")
        with open(path, "wb") as handle:
            handle.write(data)
        print(f"{name}: {len(data)} bytes, {data.count(b'speed=')} progress records -> {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
```

Run it, then write `fixtures/ffmpeg_stderr/CAPTURE.md`: the exact command above, the ffmpeg version
the capture came from (`ffmpeg -version | head -1` with `LD_LIBRARY_PATH` set — it was
**8.1.2** on 2026-09-10), the production command being driven and where that command comes from,
and the table of sizes and progress-line counts from this task's preamble. **The fixtures are
committed as captured — never hand-edited.** If a value in the table changes on regeneration, that
is ffmpeg drift and the table is updated; it is not a reason to touch the bytes.

- [ ] **Step 2: Sanity-check the corpus against the production regex**

```bash
docker exec -w /repo dispatcharr-testrunner bash -lc 'export PATH=/dispatcharrpy/bin:$PATH; python - <<"PY"
import re
rx = re.compile(r"speed=\s*([0-9.]+)x?")
for name in ("normal", "slow-trickle", "truncation"):
    raw = open(f"apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/{name}.stderr", "rb").read()
    text = raw.decode("utf-8", "replace").replace("\r", "\n")
    lines = [l for l in text.split("\n") if "speed=" in l]
    values = [float(rx.search(l).group(1)) for l in lines]
    print(name, len(lines), "records, speed", values[0] if values else None, "->", values[-1] if values else None)
PY'
```

Expected, and these are the numbers the fixtures must carry: `normal 11 records, speed 11.5 -> 2.84`;
`slow-trickle 76 records, speed 10.7 -> 0.85`; `truncation 1 records, speed 1.82 -> 1.82`. **The
last one is the scientific-notation finding** (§ Findings item 5): the real line reads
`speed=1.82e+03x` and the production regex yields `1.82`. Record what you see; do not fix it.

- [ ] **Step 3: Write the failing test** — `test_harness_standin.py`:

```python
"""The stand-in is a real child process, spawned by the relay's own spawn helper."""

import os
import re
import signal
import time

from django.test import SimpleTestCase

from apps.proxy.live_proxy.utils import posix_spawn_proc

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.ffmpeg_stderr import CORPUS_NAMES, load, progress_lines
from .harness.process import StandInBin
from .harness.upstream import FakeUpstream

# The production regex, copied deliberately rather than imported: these tests
# assert what the shipped parser sees, and importing it would make the
# assertion move if the parser moved (input/manager.py:1065).
SPEED_RE = re.compile(r"speed=\s*([0-9.]+)x?")


def _read_exactly(stream, count, timeout=10.0):
    out = b""
    deadline = time.monotonic() + timeout
    while len(out) < count and time.monotonic() < deadline:
        chunk = stream.read(count - len(out))
        if not chunk:
            break
        out += chunk
    return out


class StandInSpawnTests(SimpleTestCase):
    def test_path_shadowing_makes_which_resolve_the_stand_in(self):
        import shutil

        with StandInBin() as binary:
            self.assertEqual(shutil.which("ffmpeg"), os.path.join(binary.path, "ffmpeg"))

    def test_path_is_restored_on_exit(self):
        before = os.environ["PATH"]
        with StandInBin():
            self.assertNotEqual(os.environ["PATH"], before)
        self.assertEqual(os.environ["PATH"], before)

    def test_the_production_spawn_helper_runs_it_and_copies_ts_bytes(self):
        with FakeUpstream() as upstream, StandInBin():
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                body = _read_exactly(proc.stdout, 8 * TS_PACKET_SIZE)
                self.assertGreater(proc.pid, 0)
                self.assertIsNone(proc.poll())
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        assert_ts_aligned(body)

    def test_the_corpus_is_real_ffmpeg_output(self):
        """Guard: the fixtures must carry a real ffmpeg preamble, not invented lines."""
        for name in CORPUS_NAMES:
            raw = load(name)
            self.assertIn(b"ffmpeg version ", raw, name)
            self.assertIn(b"Input #0, mpegts, from ", raw, name)
            self.assertIn(b"Output #0, mpegts, to 'pipe:1'", raw, name)
            self.assertIn(b"\r", raw, f"{name}: no CR separators; not a real ffmpeg capture")

    def test_the_slow_trickle_corpus_actually_falls_below_one(self):
        """Row 4's evidence: a real cumulative speed= that crosses 1.0 and stays."""
        values = [float(SPEED_RE.search(l).group(1)) for l in progress_lines("slow-trickle")]
        self.assertGreater(values[0], 5.0, "capture should start with a front-loaded lead")
        self.assertLess(values[-1], 1.0, "capture should end below 1.0")
        tail = values[-20:]
        self.assertTrue(all(v < 1.0 for v in tail), f"tail not sustained below 1.0: {tail}")

    def test_the_stand_in_replays_the_corpus_to_stderr_in_order(self):
        with FakeUpstream() as upstream, StandInBin(
            stderr_corpus="slow-trickle", stderr_interval=0.0
        ):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                seen = b""
                deadline = time.monotonic() + 10
                while b"speed=0.85x" not in seen and time.monotonic() < deadline:
                    seen += proc.stderr.read(4096) or b""
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertIn(b"ffmpeg version ", seen)
        self.assertIn(b"speed=10.7x", seen)
        self.assertIn(b"speed=0.85x", seen)
        self.assertLess(
            seen.index(b"speed=10.7x"), seen.index(b"speed=0.85x"), "records out of order"
        )

    def test_stderr_interval_paces_the_replay(self):
        """A test buys the corpus's shape at its own cadence, not ffmpeg's 38 seconds."""
        with FakeUpstream() as upstream, StandInBin(
            stderr_corpus="normal", stderr_interval=0.05
        ):
            started = time.monotonic()
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                seen = b""
                deadline = time.monotonic() + 10
                while seen.count(b"speed=") < 3 and time.monotonic() < deadline:
                    seen += proc.stderr.read(4096) or b""
                elapsed = time.monotonic() - started
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertGreaterEqual(elapsed, 0.10, "three records arrived faster than 2 intervals")
        self.assertLess(elapsed, 5.0, "replay is not being paced by stderr_interval")

    def test_exit_after_bytes_ends_the_process_with_the_given_code(self):
        with FakeUpstream() as upstream, StandInBin(
            exit_after_bytes=4 * TS_PACKET_SIZE, exit_code=3
        ):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            body = _read_exactly(proc.stdout, 4 * TS_PACKET_SIZE)
            self.assertEqual(proc.wait(timeout=10), 3)
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE)

    def test_dead_air_after_bytes_stops_output_without_exiting(self):
        with FakeUpstream() as upstream, StandInBin(dead_air_after_bytes=2 * TS_PACKET_SIZE):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                body = _read_exactly(proc.stdout, 2 * TS_PACKET_SIZE)
                self.assertEqual(len(body), 2 * TS_PACKET_SIZE)
                time.sleep(0.5)
                self.assertIsNone(proc.poll(), "stand-in exited; dead air must keep it alive")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_terminate_reaps_the_child(self):
        with FakeUpstream() as upstream, StandInBin():
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            _read_exactly(proc.stdout, TS_PACKET_SIZE)
            pid = proc.pid
            proc.terminate()
            self.assertEqual(proc.wait(timeout=5), -signal.SIGTERM)
        with self.assertRaises(OSError):
            os.kill(pid, 0)
```

The last assertion is the point of the whole task: `proc.wait()` returning `-SIGTERM` and the pid
being gone means `posix_spawn_proc`'s own `_Proc.wait` (`apps/proxy/live_proxy/utils.py:202-218`)
and `_Proc.terminate` (`:226-230`), and the `_reap` they call, executed for real. A `_Proc` fake
would have made every line of that unreachable by construction.

- [ ] **Step 4: Run to verify failure** — expected
      `ModuleNotFoundError: No module named 'apps.proxy.live_proxy.tests.harness.ffmpeg_stderr'`.
      That module is imported before `harness.process` in the test file, so it is the one that
      fails first; `harness.process` is still missing too and fails on the next run.

- [ ] **Step 5: Write `harness/ffmpeg_stderr.py`**

```python
"""Access to the captured real-ffmpeg stderr corpus.

The fixtures under fixtures/ffmpeg_stderr/ are verbatim captures from
ffmpeg 8.1.2 -- see that directory's CAPTURE.md and
scripts/capture_ffmpeg_stderr.py. Never hand-edit them: the whole point is
that no line in them was written by us. Where a shape is needed that a real
ffmpeg cannot be made to emit on demand, add it to SYNTHETIC below WITH the
reason, so the exception is visible rather than mixed into the corpus.
"""

import os

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ffmpeg_stderr")

CORPUS_NAMES: tuple[str, ...] = ("normal", "slow-trickle", "truncation")

# Lines real ffmpeg will not produce to order. Empty today, and every future
# entry needs the "why real ffmpeg cannot" half of its reason, not just a
# description of the shape.
SYNTHETIC: dict[str, tuple[str, str]] = {}


def path(name: str) -> str:
    if name not in CORPUS_NAMES:
        raise ValueError(f"unknown corpus {name!r}; expected one of {', '.join(CORPUS_NAMES)}")
    return os.path.join(FIXTURES, f"{name}.stderr")


def load(name: str) -> bytes:
    """The capture, byte for byte, CR separators included."""
    with open(path(name), "rb") as handle:
        return handle.read()


def split(name: str) -> tuple[bytes, list[bytes]]:
    """(preamble, progress records).

    ffmpeg writes the banner, the input analysis, the stream mapping and
    `Press [q] to stop` as ordinary newline-terminated output, then rewrites a
    single status line in place with CR. Splitting on CR therefore puts the
    whole preamble in the first field and one progress record in each of the
    rest -- which is also exactly how the relay's stderr reader sees them.
    """
    parts = load(name).split(b"\r")
    return parts[0], [p for p in parts[1:] if p.strip()]


def progress_lines(name: str) -> list[str]:
    """The progress records as text, for assertions about speed=/time=/bitrate=."""
    return [record.decode("utf-8", "replace") for record in split(name)[1] if "speed=" in
            record.decode("utf-8", "replace")]
```

- [ ] **Step 6: Write `harness/standin.py`**

```python
"""The stand-in program. Runs as a SEPARATE PROCESS -- imports nothing from this
repository, and must keep it that way.

It is a deliberately dumb pipe: fetch the URL it is given, copy the body to
stdout, and write a scripted sequence of lines to stderr. That is precisely the
contract input/manager.py has with ffmpeg -- stdout is dup2'd onto the pipe the
manager reads as self.socket, stderr is a pipe the stderr-reader thread drains
(input/manager.py:793-803, :904) -- so the relay cannot tell the difference,
while the test gets exact control of what the child says and when it stops.

Everything it writes to stderr is a REAL ffmpeg capture replayed from a corpus
fixture (harness/fixtures/ffmpeg_stderr/, captured by
scripts/capture_ffmpeg_stderr.py). It writes the preamble immediately and then
one progress record per --stderr-interval, so a test buys the corpus's real
shape at its own cadence instead of ffmpeg's wall clock. Nothing here invents a
progress line: see harness/ffmpeg_stderr.SYNTHETIC for the one place an
exception may be declared, and why each one is unavoidable.

Arguments, all optional except the URL, which is the last positional (the same
place `-i {streamUrl}` puts it):

  --stderr-corpus PATH   the captured .stderr file to replay
  --stderr-interval S    seconds between progress records (default 0.05); the
                         preamble is always written immediately
  --stderr-loop          restart the corpus when it runs out, instead of going
                         quiet -- for a test that must outlive the capture
  --exit-after-bytes N   exit after copying N bytes
  --exit-code N          the code to exit with (default 0)
  --dead-air-after-bytes N
                         stop writing after N bytes but stay alive
"""

import os
import sys
import threading
import time
import urllib.request

_COPY_CHUNK = 8192


def _parse(argv):
    options = {
        "stderr_corpus": None,
        "stderr_interval": 0.05,
        "stderr_loop": False,
        "exit_after_bytes": None,
        "exit_code": 0,
        "dead_air_after_bytes": None,
    }
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--stderr-corpus":
            options["stderr_corpus"] = argv[i + 1]
            i += 2
        elif arg == "--stderr-interval":
            options["stderr_interval"] = float(argv[i + 1])
            i += 2
        elif arg == "--stderr-loop":
            options["stderr_loop"] = True
            i += 1
        elif arg == "--exit-after-bytes":
            options["exit_after_bytes"] = int(argv[i + 1])
            i += 2
        elif arg == "--exit-code":
            options["exit_code"] = int(argv[i + 1])
            i += 2
        elif arg == "--dead-air-after-bytes":
            options["dead_air_after_bytes"] = int(argv[i + 1])
            i += 2
        elif arg.startswith("-"):
            # Anything else -- ffmpeg's own flags, whatever the StreamProfile's
            # parameters carry -- is accepted and ignored, exactly so a test can
            # use a realistic parameter string.
            i += 1
        else:
            positional.append(arg)
            i += 1
    return options, positional


def _pump_stderr(path, interval, loop):
    """Replay a captured ffmpeg stderr stream: preamble at once, then one
    progress record per `interval`.

    ffmpeg separates the preamble from the progress records with \\r and
    rewrites one status line in place, so splitting on \\r yields the whole
    preamble first and one record after that -- and writing them back with \\r
    reproduces byte for byte what the relay's stderr reader saw from the real
    process. os.write on fd 2 rather than sys.stderr because the records carry
    no newline and text-mode buffering would hold them.
    """
    with open(path, "rb") as handle:
        parts = handle.read().split(b"\r")
    preamble, records = parts[0], [p for p in parts[1:] if p.strip()]
    os.write(2, preamble)
    while True:
        for record in records:
            if interval:
                time.sleep(interval)
            try:
                os.write(2, b"\r" + record)
            except OSError:
                return
        if not loop:
            return


def main(argv=None):
    options, positional = _parse(sys.argv[1:] if argv is None else argv)
    if not positional:
        sys.stderr.write("stand-in: no URL argument\n")
        return 2
    url = positional[-1]

    if options["stderr_corpus"]:
        threading.Thread(
            target=_pump_stderr,
            args=(options["stderr_corpus"], options["stderr_interval"], options["stderr_loop"]),
            daemon=True,
        ).start()

    copied = 0
    dead_air_at = options["dead_air_after_bytes"]
    exit_at = options["exit_after_bytes"]
    response = urllib.request.urlopen(url, timeout=30)
    try:
        while True:
            chunk = response.read(_COPY_CHUNK)
            if not chunk:
                break
            if exit_at is not None and copied + len(chunk) >= exit_at:
                os.write(1, chunk[: exit_at - copied])
                return options["exit_code"]
            if dead_air_at is not None and copied + len(chunk) >= dead_air_at:
                os.write(1, chunk[: dead_air_at - copied])
                # Alive, connected, producing nothing -- what the relay's
                # dead-air watchdog is for.
                while True:
                    time.sleep(1)
            os.write(1, chunk)
            copied += len(chunk)
    except (BrokenPipeError, OSError):
        return options["exit_code"]
    finally:
        response.close()
    return options["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Write `harness/process.py`**

```python
"""Install the stand-in as `ffmpeg`, first on PATH.

Why PATH and not a patch: posix_spawn_proc resolves its executable with
shutil.which(cmd[0]) (apps/proxy/live_proxy/utils.py:152), and
output/fmp4/manager.py:32's FFMPEG_REMUX_CMD is a module constant whose first
element is the bare string "ffmpeg". A directory placed first on PATH therefore
redirects every one of those spawns without touching a line of production code.
input/manager.py's spawn is reached the other way, through a StreamProfile row's
`command` -- see stand_in_stream_profile below -- and a profile whose command is
the literal string "ffmpeg" also selects the ffmpeg log parser
(input/manager.py:750-758), which is what the buffering-detector rows need.

The stand-in is COPIED into a temp directory rather than run in place: the
repository is bind-mounted read-only in the hook container, so nothing in the
tree can be given an exec bit at test time, and a copy that imports nothing from
this repository is a genuinely external program rather than a Python object
pretending to be one.
"""

import os
import shutil
import stat
import sys
import tempfile

from .ffmpeg_stderr import CORPUS_NAMES
from .ffmpeg_stderr import path as corpus_path

_STANDIN_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standin.py")


class StandInBin:
    """Context manager: a temp dir holding an executable `ffmpeg`, first on PATH."""

    def __init__(
        self,
        *,
        stderr_corpus: str | None = "normal",
        stderr_interval: float = 0.05,
        stderr_loop: bool = False,
        exit_after_bytes: int | None = None,
        exit_code: int = 0,
        dead_air_after_bytes: int | None = None,
    ) -> None:
        if stderr_corpus is not None and stderr_corpus not in CORPUS_NAMES:
            raise ValueError(
                f"unknown corpus {stderr_corpus!r}; expected one of {', '.join(CORPUS_NAMES)} "
                "or None for a silent stand-in"
            )
        self.stderr_corpus = stderr_corpus
        self.stderr_interval = stderr_interval
        self.stderr_loop = stderr_loop
        self.exit_after_bytes = exit_after_bytes
        self.exit_code = exit_code
        self.dead_air_after_bytes = dead_air_after_bytes
        self.path = ""
        self._previous_path = ""

    @property
    def extra_parameters(self) -> str:
        """The stand-in flags a StreamProfile's `parameters` must carry, as a string."""
        parts = []
        if self.stderr_corpus is not None:
            parts += [
                "--stderr-corpus", os.path.join(self.path, "corpus.stderr"),
                "--stderr-interval", str(self.stderr_interval),
            ]
            if self.stderr_loop:
                parts += ["--stderr-loop"]
        if self.exit_after_bytes is not None:
            parts += ["--exit-after-bytes", str(self.exit_after_bytes)]
        if self.exit_code:
            parts += ["--exit-code", str(self.exit_code)]
        if self.dead_air_after_bytes is not None:
            parts += ["--dead-air-after-bytes", str(self.dead_air_after_bytes)]
        return " ".join(parts)

    def __enter__(self) -> "StandInBin":
        self.path = tempfile.mkdtemp(prefix="dispatcharr-standin-")
        shutil.copyfile(_STANDIN_SOURCE, os.path.join(self.path, "standin.py"))

        if self.stderr_corpus is not None:
            shutil.copyfile(
                corpus_path(self.stderr_corpus), os.path.join(self.path, "corpus.stderr")
            )

        wrapper = os.path.join(self.path, "ffmpeg")
        body = (
            f"#!{sys.executable}\n"
            "import runpy, sys, os\n"
            "sys.argv[0] = 'ffmpeg'\n"
            f"sys.argv[1:1] = {self._defaults_for_wrapper()!r}\n"
            f"runpy.run_path(os.path.join({self.path!r}, 'standin.py'), run_name='__main__')\n"
        )
        with open(wrapper, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        self._previous_path = os.environ["PATH"]
        os.environ["PATH"] = self.path + os.pathsep + self._previous_path
        return self

    def _defaults_for_wrapper(self) -> list[str]:
        """Stand-in flags injected by the wrapper itself.

        The fMP4 and Output Profile spawns use a command this harness does not
        build (FFMPEG_REMUX_CMD, and an OutputProfile row), so their arguments
        cannot carry these flags. Baking them into the wrapper means every
        spawn of this stand-in behaves the way the test asked for, however it
        was reached.
        """
        return self.extra_parameters.split() if self.extra_parameters else []

    def __exit__(self, *exc) -> None:
        if self._previous_path:
            os.environ["PATH"] = self._previous_path
            self._previous_path = ""
        shutil.rmtree(self.path, ignore_errors=True)
        self.path = ""


def stand_in_stream_profile(name: str = "harness-stand-in"):
    """An unlocked StreamProfile whose command is the literal string `ffmpeg`.

    Unlocked deliberately: core/models.py:78-101 forbids editing a locked
    profile's command, and the harness has no reason to touch the seeded ones.
    """
    from core.models import StreamProfile

    profile, _ = StreamProfile.objects.get_or_create(
        name=name,
        defaults={"command": "ffmpeg", "parameters": "-i {streamUrl}"},
    )
    return profile
```

Note the ordering trap `_defaults_for_wrapper` closes, and check it holds when you run the tests:
the wrapper inserts the flags at `sys.argv[1:1]`, i.e. **before** the caller's own arguments, so the
URL stays last and `_parse`'s `positional[-1]` still finds it. If a future flag ever needs to come
after the URL, `_parse` must change, not this splice.

- [ ] **Step 8: Run the tests to verify they pass** — expected 9 tests, `OK`.

Predictable snag: `test_exit_after_bytes_ends_the_process_with_the_given_code` asserts
`proc.wait(timeout=10) == 3`. `_Proc.wait` at `apps/proxy/live_proxy/utils.py` calls
`gevent.sleep(0.01)` in its poll loop; under the unpatched test process that is a real sleep on a
per-thread hub and works (F5). If it raises because no hub exists on the calling thread, that is a
**finding about production code under test conditions** — record it in the PR description and use
`os.waitpid` directly in that one assertion; do not patch `gevent`.

- [ ] **Step 9: Run the whole package.** Expected `OK`.

- [ ] **Step 10: Commit**

Stage all of it in one `git add` — `scripts/capture_ffmpeg_stderr.py`, the three `.stderr`
fixtures, `CAPTURE.md`, `harness/ffmpeg_stderr.py`, `harness/standin.py`, `harness/process.py`,
`test_harness_standin.py` — then commit in a separate Bash call with the message in
`/tmp/2a2-msg-4.txt`. The message should say that the corpus is a verbatim capture and record the
row-4 measurement it establishes (real ffmpeg's cumulative `speed=` first touched 1.0 at 18 s and
settled below it at 20 s against a 0.25×-real-time upstream).

---

## Task 5: The relay bring-up base class and the smoke test

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/relay.py`
- Create: `apps/proxy/live_proxy/tests/test_harness_smoke.py`

**Interfaces:**
- Consumes: `FakeUpstream` (Task 3), `StandInBin`/`stand_in_stream_profile` (Task 4),
  `assert_ts_aligned`/`TS_PACKET_SIZE` (Task 2).
- Produces: `wait_until(predicate, *, timeout, interval, what)` and `RelayHarnessTestCase` with
  `upstream`, `make_channel(...)`, `tuned(...)` (the context manager, yielding `_TunedStream`),
  `tune(...)`, `stop_channel(...)`, `spawned_pid(...)`, `process_is_alive(...)`. 2a-3 … 2a-6
  subclass `RelayHarnessTestCase` and observe inside `tuned()`.

**Why `LiveServerTestCase`.** Two independent reasons, both load-bearing (F6, F7):

1. The relay reads the database from its **own OS threads with their own connections**
   (`input/manager.py:731`, on the thread started at `server.py:851`). A `django.test.TestCase`
   wraps the test in a transaction on the main thread's connection, so rows created in `setUp` are
   invisible to those threads and the tune fails with a channel that "does not exist".
   `LiveServerTestCase` is a `TransactionTestCase` and commits.
2. Since Phase 1 PR 6 the relay asks Django for its source over HTTP
   (`POST /api/relay/channels/<id>/next-source`) and posts events to `POST /api/relay/events`, and
   since PR 7 Django asks the relay back over `/proxy/relay/…`. Pointing
   `DISPATCHARR_INTERNAL_API_BASE_URL` **and** `DISPATCHARR_RELAY_BASE_URL` at
   `self.live_server_url` makes both directions real HTTP against the real views with the real
   `X-Dispatcharr-Internal` / `X-Dispatcharr-Internal-Request` headers, instead of the degraded
   "control plane unreachable" path F7 observed. Both are read per call
   (`apps/proxy/control_plane.py:66-70` and `apps/proxy/internal_base_url.py`'s `resolve_base_url`),
   so setting them in `setUp` is enough.

This is the same one-process-serves-both shape `CLAUDE.md` documents for `DISPATCHARR_ENV=dev` under
`manage.py runserver`, including the nested-request depth — and it works for the same reason:
`LiveServerTestCase`'s server is threaded, so an in-flight request can be served while another is
outstanding. `CLAUDE.md`'s warning about `--nothreading` is the same hazard; there is no equivalent
switch here.

- [ ] **Step 1: Write the failing smoke test** — `test_harness_smoke.py`:

```python
"""The harness's own smoke test: a real tune, a real child process, real TS bytes.

This is the one file in the harness allowed to look at the relay's internals --
the pid of the spawned process, the StreamManager in ProxyServer's dict --
because its subject IS the harness. Every test from 2a-3 onward asserts on
observable behaviour only (bytes, status fields, events), per the spec's
composition rule.
"""

import os

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import StandInBin, stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class HarnessSmokeTests(RelayHarnessTestCase):
    def test_a_tune_spawns_a_real_process_and_serves_real_ts_bytes(self):
        with StandInBin():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            # Everything is asserted INSIDE the tune: the response staying open
            # is what keeps the channel from starting to tear down underneath
            # the assertions (channel_shutdown_delay defaults to 0).
            with self.tuned(channel) as stream:
                body = stream.read(20 * TS_PACKET_SIZE)

                assert_ts_aligned(body)
                self.assertEqual(len(body), 20 * TS_PACKET_SIZE)
                self.assertGreaterEqual(self.upstream.request_count, 1)

                pid = self.spawned_pid(channel)
                self.assertGreater(pid, 0)
                os.kill(pid, 0)  # raises OSError if it is not a live process

            self.stop_channel(channel)
            wait_until(
                lambda: not self.process_is_alive(pid),
                timeout=10,
                what=f"the spawned process {pid} to exit",
            )

    def test_the_control_plane_is_reachable_from_the_relay(self):
        """The relay's own HTTP call to Django lands, rather than degrading."""
        from core.models import SystemEvent

        before = SystemEvent.objects.count()
        with StandInBin():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            self.tune(channel, read_bytes=4 * TS_PACKET_SIZE)
            self.stop_channel(channel)

        wait_until(
            lambda: SystemEvent.objects.count() > before,
            timeout=10,
            what="a SystemEvent row written through POST /api/relay/events",
        )
```

The second test is the one that proves reason 2 above. If `SystemEvent` is not the model
`core/relay_events.py` writes through `log_system_event()`, resolve the real one with
`git grep -n "def log_system_event" core/utils.py` and follow it to the model it saves, then use
that. **Do not** weaken the assertion to "no exception was raised": the degraded path F7 observed
raises nothing either.

- [ ] **Step 2: Run to verify failure** — expected
      `ModuleNotFoundError: No module named 'apps.proxy.live_proxy.tests.harness.relay'`.

- [ ] **Step 3: Write `harness/relay.py`**

```python
"""Bring the relay up in a backend test, against real Redis and a real control plane.

LiveServerTestCase for two reasons, both required (see the plan's Task 5):
committed rows, because the relay reads the database from its own OS threads
with their own connections; and a real HTTP control plane, because since Phase 1
PR 6 the relay asks Django for its source over HTTP and posts its events there.

The ProxyServer singleton is process-wide and is NEVER torn down: its cleanup
thread (server.py:2192) and event listener (server.py:467) are `while True`
loops with no stop flag. Tests isolate by unique channel UUID and by deleting
that channel's Redis keys, not by rebuilding the server.
"""

import contextlib
import itertools
import os
import time
import uuid as uuid_module

import requests
from django.test import LiveServerTestCase

from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .upstream import FakeUpstream


def wait_until(predicate, *, timeout: float = 10.0, interval: float = 0.05, what: str = "") -> None:
    """Poll `predicate` until it is true, or fail naming what was being waited for.

    Deadline polling, never a fixed sleep: a harness test must cost what the
    behaviour costs and no more (the plan's Keeping the suite fast).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what or 'a condition'}")


# Module-level, not per class: Channel.channel_number is a FloatField whose
# uniqueness is enforced only inside clean() and only within a channel_group
# (apps/channels/models.py:311, :411-417), so a collision would not raise -- it
# would quietly give two tests the same number and make a failure confusing.
_channel_numbers = itertools.count(9500)


class _TunedStream:
    """Exactly-`count` reads from an open streaming response, with a deadline."""

    def __init__(self, response, *, timeout: float) -> None:
        self._iterator = response.iter_content(chunk_size=4096)
        self._buffer = b""
        self._timeout = timeout

    def read(self, count: int) -> bytes:
        deadline = time.monotonic() + self._timeout
        while len(self._buffer) < count:
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"read {len(self._buffer)} of {count} bytes before the {self._timeout}s deadline"
                )
            chunk = next(self._iterator, None)
            if chunk is None:
                raise AssertionError(
                    f"upstream ended after {len(self._buffer)} of {count} bytes"
                )
            self._buffer += chunk
        out, self._buffer = self._buffer[:count], self._buffer[count:]
        return out


class RelayHarnessTestCase(LiveServerTestCase):
    """Base class for every stage-2a relay test."""

    def setUp(self):
        super().setUp()
        self._env_backup = {
            name: os.environ.get(name)
            for name in ("DISPATCHARR_INTERNAL_API_BASE_URL", "DISPATCHARR_RELAY_BASE_URL")
        }
        os.environ["DISPATCHARR_INTERNAL_API_BASE_URL"] = self.live_server_url
        os.environ["DISPATCHARR_RELAY_BASE_URL"] = self.live_server_url

        self.upstream = FakeUpstream().start()
        self.addCleanup(self.upstream.stop)
        self.addCleanup(self._restore_env)
        self._channels = []
        self.addCleanup(self._cleanup_channels)

    def _restore_env(self):
        for name, value in self._env_backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # -- fixtures ------------------------------------------------------

    def make_channel(self, *, upstream_url: str, profile):
        """A Channel with one Stream on it, wired the way a real tune expects.

        The M3UAccount/M3UAccountProfile/Stream/ChannelStream shape is copied
        from apps/proxy/tests/test_next_source_resolution.py:110-144, which is
        the recipe next_source.resolve_source() is already known to accept.
        """
        from apps.channels.models import Channel, ChannelStream, Stream
        from apps.m3u.models import M3UAccount, M3UAccountProfile

        suffix = uuid_module.uuid4().hex[:8]
        account = M3UAccount.objects.create(
            name=f"harness-account-{suffix}",
            account_type="STD",
            username="user",
            password="pass",
            max_streams=5,
        )
        # Created by M3UAccount's own post_save; fetched, not made.
        M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name=f"harness-stream-{suffix}",
            url=upstream_url,
            m3u_account=account,
            stream_profile=profile,
            stream_hash=f"harness-hash-{suffix}",
        )
        channel = Channel.objects.create(
            channel_number=next(_channel_numbers),
            name=f"harness-channel-{suffix}",
            stream_profile=profile,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        self._channels.append(channel)
        return channel

    # -- driving the relay ---------------------------------------------

    @contextlib.contextmanager
    def tuned(self, channel, *, timeout: float = 20.0):
        """GET /proxy/ts/stream/<uuid> over real HTTP; yield a reader, response open.

        Real HTTP rather than the Django test client, because the spec's
        composition rule is to drive the relay through its HTTP surface.

        The response stays open for the body of the `with`, which is what makes
        anything asserted inside it safe: channel_shutdown_delay defaults to 0
        (apps/proxy/config.py:54), so the moment the last client disconnects the
        channel may start tearing down, and a status read or a pid lookup after
        that point is racing the teardown rather than observing the stream.
        """
        url = f"{self.live_server_url}/proxy/ts/stream/{channel.uuid}"
        response = requests.get(url, stream=True, timeout=timeout)
        try:
            self.assertEqual(
                response.status_code,
                200,
                f"tune returned {response.status_code}: {response.text[:200]}",
            )
            yield _TunedStream(response, timeout=timeout)
        finally:
            response.close()

    def tune(self, channel, *, read_bytes: int = 3760, timeout: float = 20.0) -> bytes:
        """Open a tune, read `read_bytes`, close. For tests that only want bytes."""
        with self.tuned(channel, timeout=timeout) as stream:
            return stream.read(read_bytes)

    def stop_channel(self, channel) -> None:
        ProxyServer.get_instance().stop_channel(str(channel.uuid))

    # -- harness-only introspection (see test_harness_smoke.py's docstring) --

    def spawned_pid(self, channel) -> int:
        manager = ProxyServer.get_instance().stream_managers.get(str(channel.uuid))
        self.assertIsNotNone(manager, "no StreamManager for the channel")
        process = getattr(manager, "transcode_process", None)
        self.assertIsNotNone(process, "the StreamManager spawned no process")
        return process.pid

    @staticmethod
    def process_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    # -- cleanup -------------------------------------------------------

    def _cleanup_channels(self):
        server = ProxyServer.get_instance()
        for channel in self._channels:
            channel_id = str(channel.uuid)
            try:
                server.stop_channel(channel_id)
            except Exception:
                pass
            client = server.redis_client
            if client is None:
                continue
            for pattern in (
                f"{RedisKeys.channel_metadata(channel_id)}",
                f"{RedisKeys.buffer_chunk_prefix(channel_id)}*",
                f"live:channel:{channel_id}:*",
            ):
                for key in client.scan_iter(match=pattern, count=500):
                    client.delete(key)
        self._channels = []
```

- [ ] **Step 4: Run the smoke test**

```bash
… python manage.py test --keepdb apps.proxy.live_proxy.tests.test_harness_smoke -v2
```

Expected: 2 tests, `OK`, in well under 10 seconds.

Snags to expect, each with a resolution rather than a guess:

- **`RedisKeys.channel_metadata(channel_id)` and `RedisKeys.buffer_chunk_prefix(channel_id)` were
  verified at `redis_keys.py:8` and `:23`** and both take exactly the channel id. The third scan
  pattern (`live:channel:{id}:*`) is the belt to that braces and covers the whole family regardless,
  including the seven `output_*` keys.
- **The tune may 403 rather than 200.** `stream_ts` authorizes inline through
  `authorize_stream` when no nginx trust marker is present
  (`apps/proxy/authorize_views.py:145-158`). An anonymous request against an ordinary channel
  streams (parity row 24), but the channel must not be `hidden_from_output` and must satisfy the
  STREAMS ACL. If it 403s, print `response.text` — the decision names its own reason — and fix the
  **fixture**, not the authorization.
- **The tune may 200 and then serve nothing for a moment.** A client sees nothing until the ring
  buffer closes a whole ~256 KB chunk (F8's third bullet, `input/buffer.py:97-100`). At loopback
  speed that is well under a second — F7's prototype reached chunk index 2 in 0.4 s — so a stall of
  more than a couple of seconds is a real fault, not chunking. Read the relay's own log by running
  with `DISPATCHARR_LOG_LEVEL=DEBUG`.
- **`M3UAccount.objects.create` enqueues a Celery task.** Expected and harmless: the broker is real
  Redis and nothing consumes it. Do not switch on eager mode (§ Global Constraints).

- [ ] **Step 5: Run the whole package, twice, to catch cross-test leakage**

```bash
… python manage.py test --keepdb apps.proxy.live_proxy apps.channels -v1
… python manage.py test --keepdb --shuffle 12345 apps.proxy.live_proxy apps.channels -v1
```

Expected: `OK` both times. A failure only under `--shuffle` means the harness leaked process-wide
state — `PATH`, an environment variable, a Redis key, or a channel left running. Fix the leak in the
harness; do not reorder the tests.

- [ ] **Step 6: Commit** (message to `/tmp/2a2-msg-5.txt`; separate `git add` / `git commit -F`).

---

## Task 6: The real-ffmpeg escape hatch

**Files:**
- Modify: `apps/proxy/live_proxy/tests/harness/asset.py` (append)
- Modify: `apps/proxy/live_proxy/tests/test_harness_smoke.py` (append one test)

**`<ISSUE>` in the code below is a real issue number, not a placeholder to leave in.** The
orchestrator filed the two-librist image defect as an issue on `D10Scot/Dispatcharr` and supplies
the number; it belongs in that comment and in `fixtures/ffmpeg_stderr/CAPTURE.md`. **If you reach
this task without a number, ask for it before committing** — do not invent one, do not drop the
sentence, and do not file the issue yourself (`gh` without `--repo D10Scot/Dispatcharr` resolves to
upstream's public tracker).

**Interfaces:**
- Consumes: nothing new.
- Produces: `require_real_ffmpeg() -> str` (returns the executable path, or raises
  `unittest.SkipTest` naming why), `ffmpeg_env() -> dict` and
  `build_real_ts_asset(seconds: float = 2.0) -> bytes`.
  **2a-6 depends on both** for the fMP4 work — `output/fmp4/generator.py` and
  `output/fmp4/buffer.py` parse `moof`/`moov` boxes only a real remux produces.

- [ ] **Step 1: Write the failing test** — append to `test_harness_smoke.py`:

Add `from django.test import SimpleTestCase` to this file's imports — this class needs neither the
live server nor the fake upstream, and inheriting `RelayHarnessTestCase` would pay for both for
nothing.

```python
class RealFfmpegTests(SimpleTestCase):
    def test_real_ffmpeg_remuxes_the_harness_asset(self):
        """The capability 2a-6 needs: bytes a real remuxer produced."""
        import subprocess

        from .harness.asset import build_real_ts_asset, require_real_ffmpeg

        executable = require_real_ffmpeg()
        source = build_real_ts_asset(seconds=1.0)
        assert_ts_aligned(source)

        completed = subprocess.run(
            [
                executable, "-hide_banner", "-loglevel", "error",
                "-f", "mpegts", "-i", "pipe:0", "-c", "copy",
                "-f", "mp4",
                "-movflags", "frag_keyframe+delay_moov+default_base_moof",
                "pipe:1",
            ],
            input=source,
            capture_output=True,
            env={**os.environ, "LD_LIBRARY_PATH": "/usr/local/lib"},
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[:400])
        self.assertIn(b"moof", completed.stdout)
```

- [ ] **Step 2: Run to verify failure** — expected
      `ImportError: cannot import name 'build_real_ts_asset'`.

- [ ] **Step 3: Append to `harness/asset.py`**

The four imports below go at the **top** of the file, with the module docstring above them; the rest
is appended after `assert_ts_aligned`.

```python
import os
import shutil
import subprocess
import unittest

# The relay's own production environment sets this (docker/entrypoint.sh:102).
# Neither test context runs that entrypoint -- the hook container starts with
# `--entrypoint sleep` and backend-tests.yml with `options: --entrypoint ""` --
# and the image carries two librist (/usr/local/lib/librist.so.4.11.0, what
# ffmpeg was linked against, and the distro's 4.3.1 that `vlc` pulls in), with
# ld.so.conf putting the multiarch directory first. So an unqualified `ffmpeg`
# in a test resolves 4.3.1 and dies with
#   symbol lookup error: undefined symbol: rist_peer_config_defaults_set_versioned
# Verified in dispatcharr-testrunner on 2026-09-10.
#
# Set here, in the CHILD's environment, rather than in
# scripts/ci_bootstrap_backend.sh: this is test-local, works identically in the
# hook container, in backend-tests.yml and on a developer's machine, needs no
# production-adjacent edit, and does not pretend to fix what is really an image
# defect. The root cause is tracked as D10Scot/Dispatcharr#<ISSUE>.
_FFMPEG_ENV = {"LD_LIBRARY_PATH": "/usr/local/lib"}


def ffmpeg_env() -> dict:
    """`os.environ` plus whatever a spawned ffmpeg needs to actually load."""
    return {**os.environ, **_FFMPEG_ENV}


def require_real_ffmpeg() -> str:
    """The path to a WORKING ffmpeg, or skip the test saying why there isn't one.

    Skips rather than fails: whether ffmpeg links correctly is a property of the
    image the suite happens to run in, not of the code under test, and a red
    suite on an image that links differently teaches nobody anything.
    """
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise unittest.SkipTest("no ffmpeg on PATH")
    try:
        completed = subprocess.run(
            [executable, "-hide_banner", "-version"],
            capture_output=True,
            env=ffmpeg_env(),
            timeout=30,
        )
    except OSError as exc:
        raise unittest.SkipTest(f"ffmpeg at {executable} could not be run: {exc}") from exc
    if completed.returncode != 0:
        raise unittest.SkipTest(
            f"ffmpeg at {executable} exits {completed.returncode}: "
            f"{completed.stderr.decode(errors='replace')[:200]}"
        )
    return executable


def build_real_ts_asset(seconds: float = 2.0) -> bytes:
    """A short, genuinely encoded MPEG-TS, for the tests that need a real remux.

    Mirrors e2e-upstream/scripts/make-asset.sh, trimmed: no burned-in frame
    counter (nothing here decodes video) and a much shorter duration. Nothing
    downstream may hardcode the packet count -- an ffmpeg version drift is
    expected to change it.
    """
    executable = require_real_ffmpeg()
    completed = subprocess.run(
        [
            executable, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "400k", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            "-f", "mpegts", "pipe:1",
        ],
        capture_output=True,
        env=ffmpeg_env(),
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "ffmpeg failed to build the asset: "
            + completed.stderr.decode(errors="replace")[:400]
        )
    data = completed.stdout
    assert_ts_aligned(data)
    return data
```

`build_real_ts_asset` writes to `pipe:1` rather than a file: the repository mount is read-only in
the hook container, and a pipe avoids needing a temp path at all. Measured cost of the equivalent
2-second encode in the container: **25 ms**.

- [ ] **Step 4: Run the test to verify it passes — or skips for the documented reason**

```bash
… python manage.py test --keepdb apps.proxy.live_proxy.tests.test_harness_smoke -v2
```

Expected on the hook container: `OK`, 3 tests, with the third **passing** — `require_real_ffmpeg()`
sets `LD_LIBRARY_PATH` itself. If it *skips*, read the skip message: it names the failure exactly,
and a skip is the designed outcome on an image where ffmpeg genuinely cannot run. **Record which
happened in the PR description**, because 2a-6's plan depends on the answer.

- [ ] **Step 5: Run the whole package.** Expected `OK`.

- [ ] **Step 6: Commit** (message to `/tmp/2a2-msg-6.txt`; separate `git add` / `git commit -F`).

---

## Task 7: The harness README, the `CLAUDE.md` correction, and the gate

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/README.md`
- Modify: `CLAUDE.md` (§ Testing)

**Interfaces:**
- Consumes: everything above.
- Produces: the documentation 2a-3 … 2a-6 read before writing their first test, and a `CLAUDE.md`
  that no longer states something this PR makes false.

- [ ] **Step 1: Write `harness/README.md`**

Cover, in this order, and no more:

1. **What this is** — a real-subprocess, real-fake-upstream, real-Redis harness for stage 2a of the
   Phase 2 relay extraction; the first backend tests in this repository that spawn a process.
2. **The stated rule**, quoted verbatim from § The seam decision above ("Every spawn is real…").
3. **How a spawn is reached without a patch** — `StreamProfile.command` for `input/manager.py`,
   `PATH` for `FFMPEG_REMUX_CMD`, an `OutputProfile` row for `output/profile/manager.py`, with the
   three `file:line` citations.
4. **The composition rule**, quoted from the spec: drive through the HTTP surface, assert on
   observable behaviour, never on an internal call count — and the one exception,
   `test_harness_smoke.py`, whose subject is the harness itself.
5. **Writing a test**: subclass `RelayHarnessTestCase`; enter a `StandInBin`; `make_channel`;
   `tune`; assert; `stop_channel`. Ten lines of real example, copied from the smoke test.
6. **The fault vocabulary table** from Task 2, including the four not ported and why — this is what
   2c's Go fixtures copy; and **the stderr corpus**: what each of the three fixtures carries, that
   they are verbatim captures that must never be hand-edited, how to regenerate them
   (`scripts/capture_ffmpeg_stderr.py`), and that `harness/ffmpeg_stderr.SYNTHETIC` is the only
   place a hand-written line may be declared, with its reason.
7. **Time**: what is compressible and what is not (F8's three bullets), the deadline-polling rule,
   and the ≤ 15 s stage budget.
8. **The two environment facts that bite**: ffmpeg needs `LD_LIBRARY_PATH=/usr/local/lib` in both
   test containers (F4); `manage.py test` is not gevent-monkey-patched (F5).
9. **What the harness deliberately does not do**: no nginx (so no `auth_request`; the tune
   authorizes inline), no second process for the control plane (one Django serves both ends), no
   Docker.

- [ ] **Step 2: Correct `CLAUDE.md`**

Find the sentence with:

```bash
git grep -n "No backend unit test spawns a subprocess" CLAUDE.md
```

Replace that clause so it states what is now true, keeping the surrounding sentence's shape and its
following clause about the e2e suite. The replacement must say three things: the backend suite now
*can* spawn a subprocess; the capability lives in `apps/proxy/live_proxy/tests/harness/`; and the
program it spawns is a scripted stand-in reached through a `StreamProfile` row and `PATH`, with real
ffmpeg reserved for the tests that need a real remuxer's bytes. Add one sentence naming
`scripts/coverage_live_path.sh` as the live-path coverage command, and stating that it is not yet
CI-enforced (2a-7 does that).

Do **not** touch any other line of `CLAUDE.md`. In particular, leave the coverage percentages alone:
this PR adds a handful of harness tests and does not move the live-path number meaningfully, and
2a-7 is the PR that makes a coverage claim.

- [ ] **Step 3: Run the PR's gate, in full**

```bash
docker exec -w /repo dispatcharr-testrunner bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH DISPATCHARR_ENV=aio POSTGRES_HOST=/var/run/postgresql \
     POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432 \
     REDIS_HOST=localhost REDIS_PORT=6379 REDIS_DB=0 \
     CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
     DJANGO_SECRET_KEY=ci-test-secret-key DISPATCHARR_LOG_LEVEL=WARNING; \
   scripts/coverage_live_path.sh'
```

Three things must be true, and all three go in the PR description:

1. The three labels are green under `coverage` — including the new harness tests, which is the gate's
   "harness's own smoke test green under `coverage`" clause.
2. The final line reads `coverage_live_path: statements 7978  missing <n>  coverage <p>%`. The
   denominator must still be **7,978**: this PR adds no production module, so a different
   denominator means the rcfile changed shape. `missing` will be a little **below** 3,977 — the
   harness tests execute real relay code — and `<p>` a little above 50.15%. Both are the expected
   direction; record the exact numbers.
3. Nothing prints a `CoverageWarning`.

The spec's ±70-statement band is about comparing *different measurement shapes*, and this is the
shape. Do not treat it as a tolerance on this number: a denominator that is not 7,978 is a finding.

- [ ] **Step 4: Measure the runtime cost**

```bash
… time python manage.py test --keepdb apps.proxy.live_proxy -v1
```

Compare against `git stash`-ing the branch's test files, or against the same command on `main`.
Budget is **≤ 6 s added** (§ Keeping the suite fast). If it is over, the usual cause is a
`wait_until` timeout being reached rather than a predicate holding — a timeout that fires is a
failing test, but a *slow* predicate is a design problem. Report the number either way.

- [ ] **Step 5: Run the frontend and guard suites — expect them untouched**

```bash
cd e2e && npx tsc --noEmit
```

Expected: clean. This PR adds no TypeScript, so a failure here is a pre-existing condition, not
yours — say so and move on.

- [ ] **Step 6: Commit** (message to `/tmp/2a2-msg-7.txt`; separate `git add` / `git commit -F`).

- [ ] **Step 7: Write the PR description**

It must record, because the spec's gate for 2a-2 names them:

1. **The seam decision and its reasoning** — option (b), real subprocesses throughout, reached
   through `StreamProfile.command` and `PATH` rather than through an extracted seam, with the three
   reasons from § The seam decision, the portability argument (2c's Go relay spawns the stand-in
   unchanged), and the 7 ms measurement.
1a. **That every stderr line the stand-in emits is a real ffmpeg capture**, with the corpus table
   from Task 4 and the row-4 measurement it establishes: against a genuinely 0.25×-real-time
   upstream, real ffmpeg's cumulative `speed=` needed 18 s of wall clock to first touch 1.0 and 20 s
   to stay below it.
2. **`scripts/coverage_live_path.sh`'s first number**, and the fact that it reproduces the spec's
   7,978 / 3,977 / 50.2% baseline exactly under a self-contained rcfile.
3. **The three findings against the spec** listed in § Findings against the spec below.
4. **The runtime cost** measured in Step 4.
5. **Whether the real-ffmpeg test passed or skipped** (Task 6, Step 4).

Do **not** push and do **not** open the PR from this session unless the orchestrator asks.

---

## Findings against the spec, to carry into the PR description

Five, all verified, none blocking. The fourth is against `CLAUDE.md`; the fifth is a defect in
production code, found by capturing real ffmpeg output — which is the whole argument for doing so.

1. **§ Stage 2a › Gate 2's "Corrected shape" command does not produce the numbers printed beneath
   it** (F1). Run from the repository root it hits `./.coveragerc`, whose `source =` makes coverage
   ignore `--include` with a `CoverageWarning`, and it has no report step to re-apply the filter. The
   *numbers* are right; the command is not. Task 1 supersedes it with an rcfile.
2. **The denominator depends on `source`, not `include`** (F2). Reproducing 7,978 requires
   coverage's unexecuted-file walk, because `input/http_streamer.py` (101 statements, 0%) is
   imported by nothing. An implementer who follows the spec's `--include=` wording literally, in a
   script that isolates its config, lands on 7,877 and a floor that silently excludes any file that
   goes completely untested.
3. **`ffmpeg` cannot run in either test container** (F4), so the spec's assumption that a real-ffmpeg
   route is simply "available" is half true: the binary is there, the loader picks the wrong
   `librist`, and `LD_LIBRARY_PATH=/usr/local/lib` — which production sets at
   `docker/entrypoint.sh:102` and neither test context runs — is required. This is the strongest
   practical argument against making real ffmpeg the harness's default child process, and 2a-6
   inherits it.
4. **`CLAUDE.md` § State overstates the ring buffer's chunk size** (F8's third bullet). It says
   "**~1.06 MB chunks** — `TS_PACKET_SIZE * 5644`, `input/buffer.py` `target_chunk_size`, override
   `BUFFER_CHUNK_SIZE`". The override is not an override: `ConfigHelper.get` is `getattr(Config,
   name, default)`, `BaseConfig.BUFFER_CHUNK_SIZE` is defined at `apps/proxy/config.py:15` as
   `188 * 1361`, so the effective chunk is **255,868 bytes (~256 KB)** and the `5644` literal is
   dead. The consequence `CLAUDE.md` draws from it — "at a 54 KB/s trickle a chunk takes ~20s to
   roll" — is therefore roughly 4× too pessimistic (~4.7 s). Report it; do not fix it in this PR.
5. **`ffmpeg_speed` is mis-parsed when ffmpeg reports `speed=` in scientific notation.** The
   production regex is `re.search(r'speed=\s*([0-9.]+)x?', stats_line)`
   (`apps/proxy/live_proxy/input/manager.py:1065`); `[0-9.]+` stops at the `e`. Against the real
   line in `truncation.stderr` — `speed=1.82e+03x`, which ffmpeg 8.1.2 emitted unprompted on a
   truncated input — it yields **1.82** instead of 1820, a 1000× under-report. **Bounded honestly:**
   the failover consequence is nil, because a mis-parsed *high* speed is still above
   `buffering_speed`'s 1.0 default and triggers nothing. What is wrong is the **displayed**
   `ffmpeg_speed` on `GET /proxy/ts/status/<uuid>` and `GET /proxy/relay/channels`, which is
   externally observable and therefore parity-matrix territory. The mirror-image case — a very small
   speed rendered as `9.5e-05x` and parsed as **9.5**, which *would* suppress a buffering failover —
   is real in the regex but not reachable in practice: `speed = media_time / wall_time`, so
   `< 1e-4` needs the wall clock to run more than 10,000× ahead of the media, and no capture here
   came close. Report it as a candidate parity-matrix row for **2a-4** (whose subject is
   `input/manager.py` and rows 1-6), with the reachable half and the unreachable half distinguished.
   **Do not fix it** — D5 is strict parity, defects included.

---

## Verification command

Every "run the tests" step in this plan means:

```bash
docker exec -w /repo dispatcharr-testrunner bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH DISPATCHARR_ENV=aio POSTGRES_HOST=/var/run/postgresql \
     POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432 \
     REDIS_HOST=localhost REDIS_PORT=6379 REDIS_DB=0 \
     CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
     DJANGO_SECRET_KEY=ci-test-secret-key DISPATCHARR_LOG_LEVEL=WARNING; \
   python manage.py test --keepdb <label> -v2'
```

If the container is not running, `.claude/hooks/start-test-container.sh` recreates it (idempotent,
~2 s). **The repository is bind-mounted read-only at `/repo`**, so the container sees your edits
immediately and can write nothing back — every path the harness writes to must be under `/tmp`,
which is why `StandInBin` uses `tempfile.mkdtemp()` and `build_real_ts_asset` writes to a pipe.

If Docker is down, the hook says so and exits 0. **Then say the tests did not run — do not describe
the work as verified.**

---

## Done criteria

- [ ] `scripts/coverage_live_path.sh` runs, prints `statements 7978`, and refuses to report over a
      data file it did not stamp.
- [ ] `apps/proxy/live_proxy/tests/harness/` holds the eight modules, the three committed corpus
      fixtures with their `CAPTURE.md`, and the README of § File
      structure.
- [ ] `test_harness_upstream.py`, `test_harness_standin.py` and `test_harness_smoke.py` are green,
      under `coverage`, in the run of Task 7 Step 3.
- [ ] `apps.proxy.live_proxy` and `apps.channels` are green in default order **and** under
      `--shuffle 12345`.
- [ ] `CLAUDE.md` no longer says no backend test spawns a subprocess.
- [ ] No file outside § File structure is modified — in particular no production module, no
      workflow, no `pyproject.toml`, no `uv.lock`, no `docs/relay-parity-matrix.md`, no `e2e/`.
- [ ] The PR description carries the five items of Task 7 Step 7.
