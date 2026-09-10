# Phase 2 PR 2a-4 — `input/manager.py` Behaviour Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the three failover triggers, the `speed=` arming delay, the mid-stream
threshold snapshot, the unbounded buffering switch and the scientific-notation
under-report as behavioural tests driven through the relay's HTTP surface — closing
parity-matrix rows 1-6 and 28 and raising measured coverage on
`apps/proxy/live_proxy/input/manager.py`.

**Architecture:** Every test is a `RelayHarnessTestCase` (2a-2): a real Django control
plane on a live server, real Redis, a real in-process fake upstream, and a real child
process installed on `PATH` as `ffmpeg` replaying a **captured real-ffmpeg stderr
corpus**. Nothing mocks `StreamManager`. The only patched objects are configuration
(`apps/proxy/config.py`'s `TSConfig` and the `proxy_settings` `CoreSettings` group),
which is the production lever, not a seam. Assertions are on what a client and an admin
can see: the bytes the tune serves, `GET /proxy/relay/channels/<uuid>`, and the
`SystemEvent` rows the relay's own `POST /api/relay/events` writes.

**Tech Stack:** Python 3.13, Django 6, `manage.py test` (custom runner), the 2a-2 harness
under `apps/proxy/live_proxy/tests/harness/`, `coverage` 7.16 via
`scripts/coverage_live_path.sh`, the parity-matrix guard in the `guards` Playwright
project.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` at `0c7e19a4`
(worktree `.worktrees/phase2-spec`, PR #225) — § Verified facts, § Testing,
§ The subprocess harness, Gate 2, and the `2a-4` row of § The seven PRs.
The harness it consumes is specified by
`docs/superpowers/plans/2026-09-10-phase2-2a2-subprocess-harness.md` (on this branch).

---

## Global Constraints

Exact values, copied from the spec, `CLAUDE.md`, and the branch. Every task's
requirements implicitly include this section.

- **Branch:** `migration/phase2a-manager-coverage`, stacked on
  `migration/phase2a-subprocess-harness` at `2a826e07`. Worktree
  `/Users/dion/git/Dispatcharr/.worktrees/phase2-2a4`. Run every command from there,
  with absolute paths.
- **Composition rule (spec § The subprocess harness, final paragraph):** drive the relay
  through its **HTTP surface** against **real dependencies** — the fake upstream, real
  Redis, real spawned children — **never against mocks of `input/manager.py`'s
  internals.** Ask of every assertion whether it still means anything when the
  implementation underneath is Go. `test_harness_smoke.py`'s module docstring is
  explicit that it is the *one* file allowed to look at the relay's internals; nothing
  in this PR may.
- **D5 is strict parity, defects included.** Rows 6 (#221) and 28 (#227) are defects the
  Go relay must reproduce. **Pin the wrong behaviour, and say so in the test's name or
  docstring** so nobody later "fixes" it.
- **Never hard-code a value read off a capture.** Three independent captures gave
  `0.847x`, `0.846x` and a third figure for the same fixture, and the `truncation`
  mantissa moved across all three. `harness/fixtures/ffmpeg_stderr/CAPTURE.md` forbids
  tabulating digits. Every literal a test compares against a corpus is **derived from
  the corpus at test time**, and every relationship the test needs from the corpus
  (a lead above a threshold, a sustained tail below it, a scientific-notation record)
  is **asserted, with a message telling a future reader to re-derive**.
- **`buffering_speed` is bounded to `[0.1, 10.0]` and `buffering_timeout` is an
  integer in `[0, 300]`** (`core/serializers.py:95-96`). Every threshold this PR sets
  is one an operator could set through the UI. Do not write a value the API would
  reject.
- **Files this PR may create or modify — nothing else:**
  - create `apps/proxy/live_proxy/tests/manager_support.py`
  - create `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`
  - create `apps/proxy/live_proxy/tests/test_manager_connection_failover.py`
  - modify `docs/relay-parity-matrix.md` (seven Pin cells, one Notes cell)
  - modify `metrics/curated/defects.yml` (one status flip, one new entry)
  - create this plan (already done)
  **In particular: do not touch `apps/proxy/live_proxy/tests/harness/`,
  `scripts/coverage_live_path.*`, `e2e/tests/guards/`, any production module,
  `CLAUDE.md`, or any workflow.** 2a-3, 2a-5 and 2a-6 are editing this tree in
  parallel from the same base; `harness/` and the guard are the files they would
  collide on.
- **`HIGHEST_ROW_ID` stays 28.** This PR adds no matrix row. (§ Findings F5 records the
  row it would have added, and why it does not.)
- **Matrix edits obey `docs/relay-parity-matrix.md`'s own comment block:** one row is
  one line, cells are never padded, no stored counts, do not sort, do not run a
  Markdown formatter over the file. Closing a row is a one-line diff.
- **Test-suite cost: build all eight tests and state the cost. Do not cut a test to
  meet a time budget.** `apps.proxy.live_proxy.tests` is **179 tests in 7.006 s** on
  this branch (measured, § F1). This PR adds **≈8.5 s** (measured on a review container,
  § F9). **The ≤15 s stage ceiling is withdrawn** and replaced by per-PR measurement with
  a reconsideration trigger at 45 s on this label — see § Rulings (a). Measure with
  `--durations`, state the number, and do not optimise further.
- **Attribution:** every commit message ends with

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
  ```

  Write the message to a file and use `git commit -F <file>` — the `PreToolUse` hook
  matches on command text, so a heredoc containing "git commit" trips it. **Stage and
  commit in separate `Bash` calls.**
- **Do not push and do not open a PR.**

---

## Rulings this plan carries

Three questions this plan raised were put to the orchestrator and answered. They are
recorded here because they change what the implementer does, not merely what the PR
description says.

**(a) The ≤15 s stage ceiling is withdrawn; build all eight tests.** The ceiling was a
guard against making the commit hook unusable, not a goal, and cutting tests to meet a
time budget *in the PR whose purpose is coverage* is backwards — the drop order in § F9
costs either the Proxy path (the largest coverage item here) or row 5's falsifiability.
It is replaced by **per-PR measurement with a reconsideration trigger at 45 s on the
`apps.proxy.live_proxy` label**. At the measured ≈8.5 s this PR is comfortably inside
that. The lever this plan identified, `available_apps` on `RelayHarnessTestCase`, went to
2a-2, which owns that base class. Keep § F9's drop order, marked as a contingency that
was not taken.

**(b) `COVERAGE_CORE=sysmon` is adopted, and the four coverage PRs re-take their
baselines under it.** § Findings F2's under-count and the shape guard's failure to stamp
the tracer core are both dispatched to 2a-2, under one condition imposed there and not
here: 2a-2 verifies on a concrete example that the extra credit is for **genuinely
executed** lines before adopting, because a tracer that over-credits an 80 % gate would be
worse than one that under-counts. **What this means for 2a-4:** measure the baseline and
the new figure under **whatever tracer core `scripts/coverage_live_path.sh` selects at the
time you implement**, and if that changed while this PR was in flight, re-take the
baseline rather than reuse an older number. This is cheap here precisely because the gate
is worded as a same-session back-to-back delta rather than an absolute count.

**(c) Row 2's Notes cell is amended, as Task 4 Step 4 specifies.** Notes cells are not
immutable; a half-pinned row that looks whole is worse than one that says which half is
pinned, and the matrix's readers in 2c are the audience that matters.

---

## Verified facts this plan rests on

All measured in a dedicated container
(`dispatcharr-testrunner-2a4`, image `ghcr.io/d10scot/dispatcharr:latest`) on
`2a826e07`, 2026-09-10. Re-measure only if you doubt one; do not re-derive them by
reading.

### F1 — The branch's coverage and test-time baseline

`scripts/coverage_live_path.sh`, full three-label run:

```
TOTAL                                                7978   3216    60%
apps/proxy/live_proxy/input/manager.py               1248    498    60%
apps/proxy/live_proxy/input/http_streamer.py          101    101     0%
coverage_live_path: statements 7978  missing 3216  coverage 59.69%
```

`python manage.py test --keepdb apps.proxy.live_proxy.tests` → **179 tests in 7.006 s**.
`test_harness_smoke` alone: **3 tests in 2.390 s**, of which
`test_a_tune_spawns_a_real_process_and_serves_real_ts_bytes` is 1.089 s and
`test_the_control_plane_is_reachable_from_the_relay` is 0.713 s. **Treat ~0.7 s as the
fixed cost of one `RelayHarnessTestCase` tune** — flush, live server, channel rows,
spawn, first chunks — before any waiting this PR adds.

The spec's "771 missed on `input/manager.py`" is the `a948cd8a` figure from before the
harness existed. **The number this PR moves is 498, not 771.**

### F2 — Coverage does not see statements that execute after a greenlet switch

Reduced case, run in the container:

```python
# mod.py
import gevent
def work(n):
    total = 0                 # traced
    for i in range(n):        # traced
        gevent.sleep(0)       # traced
        total += i            # NOT traced
    tail = total * 2          # NOT traced
    return tail               # NOT traced
```

Driven once from a `threading.Thread` and once from the main thread,
`coverage run --include=mod.py` reports **lines 7-9 missing**. Adding
`concurrency = gevent` to the rcfile reports 100%; `COVERAGE_CORE=sysmon` also reports
100%, with no `concurrency` setting.

This is why `input/manager.py:942-983` — the whole of `_read_stderr`'s CR/LF splitting
loop, including the `self._parse_ffmpeg_stats(line_text)` call at `:962` — is reported
missing while `_parse_ffmpeg_stats` itself (`:1058-1204`) is largely covered: `:940` is
`gevent.sleep(0)`. The same effect hides `fetch_chunk`'s body (`:1774` onward is missing
although `_process_stream_data:1317-1328` is covered).

**Consequences for this PR, and they are not optional reading:**

1. **A red line is not proof a test did not run it.** Do not chase `_read_stderr`'s
   or `fetch_chunk`'s missing lines; they cannot go green under the committed rcfile.
2. **The measured increase will be materially smaller than the behaviour pinned.**
   Size the gate on the delta you measure, never on a statement count derived by
   reading the source.
3. **Do not change the rcfile or the script.** `concurrency = gevent` was measured on
   the real suite and is *worse*: 3,877 missed instead of 3,216, because the test
   process is not monkey-patched and gevent mode stops tracing the relay's plain OS
   threads. `COVERAGE_CORE=sysmon` is better (3,114 missed, `input/manager.py` 474) and
   **has been adopted** — but the change belongs to 2a-2, which owns
   `scripts/coverage_live_path.*`, and it is conditional on 2a-2 first verifying that
   the extra credit is for genuinely executed lines (§ Rulings (b)). **What 2a-4 does
   about it: measure under whatever core the script selects at implementation time, and
   re-take the baseline if that changed while this PR was in flight.**

### F3 — The corpus, as it is on this branch

`harness/fixtures/ffmpeg_stderr/`, ffmpeg 8.1.2, captured 2026-09-10:

| Fixture | records | CR bytes | shape this PR uses |
|---|---|---|---|
| `normal` | 11 | 10 | opens above 10.0x, every later record below it, never crosses 1.0 |
| `slow-trickle` | 76 | 75 | opens above 10.0x; crosses below 1.0 partway and stays below for a long tail |
| `truncation` | 1 | 0 | one LF-terminated `Lsize=` record whose `speed=` is in scientific notation |

**Verified relationships this PR depends on, each of which its tests assert rather than
assume:**

- `slow-trickle`'s first record is above 10.0 and **every later record is below it** —
  so `buffering_speed = 10.0` (the API maximum) gives a genuine above-then-below
  transition with a ~75-record run below the threshold. That is the lever rows 1 and 6
  use, and it is the one `CLAUDE.md` § Known defects names ("`buffering_speed` above
  1.0 is the lever").
- `normal`'s first record is above 10.0 and every later record is below it, and its
  minimum is above 0.1 (the API minimum) — so `buffering_speed = 0.1` is a threshold
  nothing in `normal` can trip. That is the lever row 5 uses.
- `slow-trickle`'s first record below **1.0** (the default `buffering_speed`) carries an
  `elapsed=` field well past ten seconds. That is parity row 4's arming delay, read off
  the capture rather than waited out.
- `truncation`'s one record's `speed=` matches `[0-9.]+e[+-][0-9]+`, and the value the
  production regex reads is smaller than the true value by more than 100×.

### F4 — The thresholds, and which are compressible

- `buffering_speed` / `buffering_timeout` are `CoreSettings` `proxy_settings` values
  (`apps/proxy/config.py:134-143`), **snapshotted into the manager at
  `input/manager.py:60-61`**, i.e. in `StreamManager.__init__` — which is parity row 5
  itself. Write the row; `CoreSettings`' `post_save` receiver
  (`core/signals.py:11-15` → `core/models.py:356-363`) drops both the Redis group cache
  and `BaseConfig`'s 10-second process-local copy.
- `HEALTH_CHECK_INTERVAL` (`apps/proxy/config.py:110`), `CONNECTION_TIMEOUT`
  (`:13`) and `MAX_STREAM_SWITCHES` (`:12`) are plain class attributes read through
  `getattr(Config, …)` / `ConfigHelper.get`. `unittest.mock.patch.object` on `TSConfig`
  is the production read path, and the spec's own reachability note plus 2a-2's F8
  sanction it. It is **not** a mock of `input/manager.py`.
- `max_unhealthy_checks = 3` (`input/manager.py:1512`), `action_cooldown = 30` (`:1513`)
  and `stable_time >= 30` (`:1536`) are **bare literals**. Nothing compresses them. A
  dead-air test costs `3 × health_check_interval` plus one inactivity threshold; the
  `stable_time >= 30` branch costs 30 s of wall clock and is therefore **not pinned by
  this PR** (§ F8).
- The retry backoff `min(.25 * failures, 3)` (`input/manager.py:556`, `:587`) costs
  `0.25 + 0.5 = 0.75 s` for three attempts. `MAX_RETRIES` is patchable, but row 3 names
  the value 3, so this PR pays the 0.75 s rather than change the number under test.

### F5 — What each row's failure is observable as

| Row | Externally observable signal | Emitting code |
|---|---|---|
| 1 | `SystemEvent(event_type='channel_failover', details['reason']='buffering_timeout', details['duration'])` | `input/manager.py:1156-1162` — **the only `channel_failover` emitter in the tree** |
| 2 | `SystemEvent(event_type='stream_switch')` + the relay's `stream_id` changes | `input/manager.py:1480-1486` (via `update_url`) |
| 3 | `SystemEvent(event_type='channel_error', details['error_type']='connection_failed', details['attempts'])` + an `Error:` TS packet in the response body | `input/manager.py:544-551`; `output/ts/generator.py:229` + `utils.py:96-98` |
| 4 | the relay's `state` never `buffering` while its `ffmpeg_speed` is ≥ the threshold | `input/manager.py:1122-1204` writes `ffmpeg_speed` (through `:1206-1230`) **before** the state (`:1190`) |
| 5 | as row 4, across a mid-stream settings write | as row 4 |
| 6 | row 1's event, with `MAX_STREAM_SWITCHES` at 0 | `input/manager.py:1134-1162` never touches `stream_switch_attempts` (`:388`, `:402`) |
| 28 | `ffmpeg_speed` on `GET /proxy/relay/channels/<uuid>`, a float | `input/manager.py:1064-1065`, `channel_status.py:373-377`, `relay_serializers.py:129` |

`relay_client.get_channel(str(uuid))` is the Django-side client for that endpoint; it
returns `ChannelStatus.get_detailed_channel_info`'s dict, built from **one `hgetall`**
(`channel_status.py:30`), so `state`, `ffmpeg_speed` and `stream_id` in one snapshot are
mutually consistent. `RelayHarnessTestCase.setUp` already points
`DISPATCHARR_RELAY_BASE_URL` at the live server (`harness/relay.py:87`), so the call
works unchanged from a test.

`emit_event` runs `post_events` **synchronously** under `manage.py test`
(`control_plane.py:329-337` — the process is not monkey-patched), and
`core/relay_events.py:175-177` passes `**details` straight into `log_system_event`,
which stores them in `SystemEvent.details` (`core/utils.py:891-896`). So
`details['reason']` etc. are real, queryable fields.

### F6 — A failover needs a second stream **on a different URL**

`next_source.resolve_source`'s failover branch rejects any candidate resolving to the
URL already playing (`apps/proxy/next_source.py:621-633`). Two `ChannelStream` rows
pointing at the same `FakeUpstream` path therefore make every failover answer "no
alternate stream", and a test built that way passes or fails for the wrong reason.

`FakeUpstream`'s handler never inspects the request path
(`harness/upstream.py:_Handler.do_GET`), so a **different path on the same server** is a
genuinely different URL serving the same bytes. `ChannelStream.order`
(`apps/channels/models.py:938-949`) is the traversal order, and
`get_alternate_streams` reads it as `channel.streams.all().order_by('channelstream__order')`
(`next_source.py:308`).

### F7 — `TransactionTestCase`'s flush leaves `proxy_settings` poisoned

Two separate mechanisms, and both need the same explicit call.

**Writing.** `get_proxy_settings` is a classmethod caching on `cls`
(`apps/proxy/config.py:32-51`), and every relay reader binds the **subclass** —
`from apps.proxy.config import TSConfig as Config` at `config_helper.py:5` and
`input/manager.py:11` — so the cached dict lands on `TSConfig` as a shadowing class
attribute. `CoreSettings`' `post_save` receiver clears **`BaseConfig`**
(`core/models.py:360-361`), which never touches that shadow. **Saving the row therefore
does not make the new value visible to the relay at all**; the 10-second
`_proxy_settings_cache_ttl` (`apps/proxy/config.py:24`) is the sole expiry. Filed as
**#232** (§ Findings F6).

**Clearing.** `TransactionTestCase._fixture_teardown` TRUNCATEs and fires **no**
`post_delete`, so a test that writes `proxy_settings` leaves its thresholds cached into
later tests in the same label — `test_harness_smoke`'s included.

**Both are handled the same way: `set_proxy_settings` calls
`TSConfig.clear_proxy_settings_cache()` after the write, and registers a cleanup that
deletes the row and calls it again.** § Findings F3 says where this belongs long term.

No existing test writes the group — `test_proxy_settings.py` patches
`TSConfig.get_proxy_settings` instead — which is why #232 had never been provoked.

### F8 — What this PR does **not** pin, stated up front

- **Row 2's "stable for ≥30 s reconnects in place first" branch.** `stable_time >= 30`
  is a literal at `input/manager.py:1536` and `connection_start_time` is set inside
  `_establish_transcode_connection` (`:888`); reaching that branch means 30 s of real
  time or reaching into the manager, and the composition rule forbids the second.
  Row 2's Notes cell is amended in Task 4 to say so.
- **`_wait_for_existing_processes_to_close` (`:205-235`, 19 statements).** Its three
  callers are `_establish_transcode_connection` when a process is still alive (never,
  after `update_url`'s `_close_socket`), `_establish_http_connection` when
  `current_response`/`current_session` is set (never on the Proxy path — `HTTPStreamReader`
  owns its own session), and `_attempt_reconnect` (the ≥30 s branch above). Out of reach
  for this PR.
- **The HLS/RTSP/UDP force-ffmpeg branch (`:441-455`).** `detect_stream_type`
  (`utils.py:31-66`) classifies the harness's `.ts` URLs as `ts`.

### F9 — The cost this PR adds, predicted

Eight tests, of which every one is a real tune: **~0.7 s fixed each (F1) plus the real
time the behaviour under test takes.** This plan first predicted 9-11 s; **a review
implementation measured 12.66 s**, on a container roughly 15 % slower than the one § F1's
figures came from, and **almost all of the overshoot was one test**. Row 2 alone cost
**5.47 s**, because `_process_stream_data` re-checks `needs_stream_switch` only between
`fetch_chunk` calls and a `fetch_chunk` on a dead-air pipe blocks in `select()` for the
whole `CHUNK_TIMEOUT` — 5 s as shipped. Patching that down to 0.2 (same config-lever
class as the other two in that chain, and re-read per call rather than snapshotted)
brings row 2 to **1.32 s** and the PR to **≈8.5 s**, still green.

**≈8.5 s is the number to expect and to state.** The ≤15 s ceiling that framed the
earlier drafts is withdrawn (§ Rulings (a)); the trigger is now 45 s on this label, and
8.5 s is comfortably inside it. Do not optimise further — measure, report, move on.

**All eight are built (§ Rulings (a)).** The drop order below is recorded as a
contingency and **was not taken**; it is here so that a later decision to cut knows what
each cut costs, not as licence to make one:

1. `test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats` — closes no matrix row,
   but is the largest single coverage item in the PR (~143 statements of
   `input/manager.py` plus a 101-statement file at 0 %).
2. Row 5's second channel — costs the test its falsifiability, which is the whole reason
   it is there.

Neither is a good trade against a slower commit hook, which is why neither was made.

### F10 — Routing and hooks

- `dispatcharr/test_discovery.py:41` already routes `apps/proxy/live_proxy/` to both
  `apps.proxy.live_proxy.tests` and `apps.channels.tests`. New files under
  `apps/proxy/live_proxy/tests/` need **no** `_PATH_ALIASES` entry and no change to
  `tests/test_ci_test_routing.py`.
- The `PostToolUse` hook runs the whole `apps.proxy.live_proxy` + `apps.channels`
  packages when you edit a `tests/test_*.py`. **It does not fire for
  `manager_support.py`** (not `test_*`) — only `scripts/check_credential_logging.py`
  does. **After every edit to `manager_support.py`, run the label yourself.**
- Editing `docs/relay-parity-matrix.md` fires no hook. Run the guard by hand
  (§ Verification commands).
- `metrics/curated/defects.yml` **does** fire a hook (`metrics/**`).

---

## File structure

Create:

| Path | Responsibility |
|---|---|
| `apps/proxy/live_proxy/tests/manager_support.py` | The levers both test modules need: the `proxy_settings` writer with its cleanup, the corpus readers, the alternate-stream builder, the status poller, the Proxy `StreamProfile`, the bounded body reader. **Not under `harness/`** — see below. |
| `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py` | Everything the ffmpeg stderr reader decides: rows 1, 4, 5, 6, 28. One class. |
| `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` | Everything the socket decides: rows 2 and 3, plus the raw-HTTP Proxy path. One class. |

Modify:

| Path | Change |
|---|---|
| `docs/relay-parity-matrix.md` | Seven Pin cells (`owed: 2a-4` → a test reference) and row 2's Notes cell. Nothing else — the `<!-- block: owed by 2a-4 -->` marker stays as it is: it names the PR that *owed* the rows, which is the grouping key the file's own comment block says never to re-sort. |
| `metrics/curated/defects.yml` | `max-stream-switches-unbounded` (#221) `open` → `pinned` with a `test:`; a new entry for #227, which 2a-2 filed but did not add to the ledger (§ Findings F4). |

**Why `manager_support.py` is not in `harness/`:** `harness/` is 2a-2's deliverable and
2a-3, 2a-5 and 2a-6 are all consuming it from the same base commit; a change there is a
merge conflict for three PRs and a re-review of the harness for each. Everything in this
module is specific to `input/manager.py`'s failover behaviour. Two of its pieces —
`set_proxy_settings` and `sample_while` — plausibly belong to every stage-2a test;
§ Findings F3 records that, and the recommendation that whichever PR lands last (or
2a-7) move them into `RelayHarnessTestCase`.

**Two test files, not one:** the two halves need different fixtures (a stderr corpus
versus a socket fault) and different config levers, and splitting them keeps each file
under ~300 lines. Two `LiveServerTestCase` classes cost two server starts, which is
milliseconds.

---

## Interfaces at a glance

What `manager_support.py` exports, in the exact spelling later tasks use:

```python
SPEED_RE: re.Pattern          # the PRODUCTION regex, copied
FULL_SPEED_RE: re.Pattern     # the same field, scientific notation included
ELAPSED_RE: re.Pattern        # ffmpeg 8.1.2's elapsed=H:MM:SS.ss
API_MIN_BUFFERING_SPEED: float = 0.1
API_MAX_BUFFERING_SPEED: float = 10.0

def corpus_speeds(name: str) -> list[float]
def corpus_elapsed(name: str, index: int) -> float
def set_proxy_settings(test, **overrides) -> dict
def proxy_stream_profile() -> StreamProfile
def add_alternate_stream(test, channel, upstream, *, order: int) -> Stream
def status(channel) -> dict | None
def sample_while(test, channel, *, until=None, chunks=None, drain=None,
                 timeout: float = 15.0) -> list[dict]
def read_until_end(response, *, timeout: float = 15.0) -> bytes
```

From the harness, unchanged (do not re-implement any of these):

```python
from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.ffmpeg_stderr import progress_lines
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
#   RelayHarnessTestCase.stand_in(**StandInBin kwargs)  -> context manager
#   RelayHarnessTestCase.make_channel(*, upstream_url, profile) -> Channel
#   RelayHarnessTestCase.tuned(channel, *, timeout=20.0)  -> context manager -> _TunedStream
#   RelayHarnessTestCase.upstream : FakeUpstream (already started, rate=1.0)
#   _TunedStream.read(count) -> bytes, with a deadline
```

---

## Task 1: The support module, and the row-28 defect pin

**Files:**
- Create: `apps/proxy/live_proxy/tests/manager_support.py`
- Create: `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`
- Modify: `docs/relay-parity-matrix.md` (row 28's Pin cell)

**Interfaces:**
- Consumes: the harness names listed in § Interfaces at a glance.
- Produces: every symbol in § Interfaces at a glance. Tasks 2-5 use them by those exact
  names and add no helpers of their own.

- [ ] **Step 1: Write `manager_support.py`**

```python
"""Levers the input/manager.py behaviour tests pull, and the corpus readers they use.

Deliberately NOT under harness/: harness/ is 2a-2's deliverable and 2a-3, 2a-5 and
2a-6 are consuming it from this same base commit, so an edit there is a merge conflict
for three PRs. Everything here is specific to input/manager.py's failover behaviour.
`set_proxy_settings` and `sample_while` are the two that plausibly belong to every
stage-2a test; the PR description records the recommendation to move them into
RelayHarnessTestCase once the parallel PRs have landed.
"""

import re
import time

from apps.proxy import relay_client
from apps.proxy.config import TSConfig
from core.models import PROXY_PROFILE_NAME, PROXY_SETTINGS_KEY, CoreSettings, StreamProfile

from .harness.ffmpeg_stderr import progress_lines

# The PRODUCTION regex, copied deliberately rather than imported: these tests assert
# what the shipped parser sees, and importing it would make the assertion move if the
# parser moved (input/manager.py:1065). Same rationale, and the same literal, as
# test_harness_standin.py:20-22.
SPEED_RE = re.compile(r"speed=\s*([0-9.]+)x?")

# The whole field, exponent included -- what the production regex declines to read.
# The gap between the two is parity-matrix row 28 / issue #227.
FULL_SPEED_RE = re.compile(r"speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?")

# ffmpeg 8.1.2 appends elapsed= after speed=; CAPTURE.md records it as one of the four
# shapes a hand-written fixture would have got wrong. Nothing in production parses it --
# it is read here only so a test can quote the capture's own wall clock.
ELAPSED_RE = re.compile(r"elapsed=(\d+):(\d\d):(\d\d(?:\.\d+)?)")

# core/serializers.py:96. The API cannot store a buffering_speed outside this range, so
# every threshold these tests set is one an operator could set.
API_MIN_BUFFERING_SPEED = 0.1
API_MAX_BUFFERING_SPEED = 10.0


def corpus_speeds(name):
    """Every progress record's speed=, as the production regex reads it."""
    return [float(SPEED_RE.search(line).group(1)) for line in progress_lines(name)]


def corpus_elapsed(name, index):
    """Record `index`'s elapsed= in seconds -- the real ffmpeg wall clock it took."""
    hours, minutes, seconds = ELAPSED_RE.search(progress_lines(name)[index]).groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _reset_proxy_settings():
    # Deleting the row fires post_delete (core/signals.py:11-13), which invalidates the
    # Redis group cache. It also calls BaseConfig.clear_proxy_settings_cache()
    # (core/models.py:360-361), which is the WRONG class and clears nothing a relay
    # reader will see -- issue #232 -- so the explicit call below is what actually
    # drops the process-local copy.
    CoreSettings.objects.filter(key=PROXY_SETTINGS_KEY).delete()
    TSConfig.clear_proxy_settings_cache()


def set_proxy_settings(test, **overrides):
    """Write proxy_settings the way an operator would, and prove the write landed.

    The explicit TSConfig.clear_proxy_settings_cache() below is REQUIRED, and the
    reason is a production defect this helper's own read-back assertion found
    (issue #232). `get_proxy_settings` is a classmethod that caches on `cls`
    (apps/proxy/config.py:32-51), and every relay reader binds the SUBCLASS --
    `from apps.proxy.config import TSConfig as Config` at config_helper.py:5 and
    input/manager.py:11 -- so the cache lands on `TSConfig` as a shadowing class
    attribute. CoreSettings' post_save receiver clears `BaseConfig`
    (core/models.py:360-361), which never touches that shadow. So saving the row
    does NOT make the new value visible; the 10-second TTL
    (apps/proxy/config.py:24) is the only thing that expires it. Without this line
    rows 1, 5 and 6 fail their own read-back whenever any test tuned a channel in
    the previous ten seconds -- which, in file order, row 28 always has.

    The cleanup is not optional either. TransactionTestCase's teardown TRUNCATEs and
    fires no post_delete, so without it the cached dict keeps this test's thresholds
    into later tests in the same label.

    The read-back assertion is what makes every test using this lever falsifiable: it
    goes through TSConfig.get_proxy_settings(), the exact reader StreamManager.__init__
    uses at input/manager.py:60-61, so a test that later observes "nothing buffered"
    cannot be passing because the setting silently failed to apply. It is also what
    caught #232 rather than letting it pass as a mysterious flake.
    """
    test.addCleanup(_reset_proxy_settings)
    merged = dict(CoreSettings.get_proxy_settings())
    merged.update(overrides)
    CoreSettings.objects.update_or_create(
        key=PROXY_SETTINGS_KEY, defaults={"value": merged}
    )
    # See the docstring: the post_save receiver clears the wrong class (#232).
    TSConfig.clear_proxy_settings_cache()
    live = TSConfig.get_proxy_settings()
    for name, value in overrides.items():
        test.assertEqual(live.get(name), value, f"proxy_settings.{name} did not apply")
    return merged


def proxy_stream_profile():
    """The locked built-in Proxy profile: raw HTTP into the ring buffer, no subprocess.

    Created rather than fetched: TransactionTestCase's flush wipes the rows
    core/migrations/0003_preload_stream_profiles.py seeds. `locked=True` is what makes
    is_proxy() true (core/models.py:127-130), and StreamProfile.save's protected-field
    guard only runs when self.pk is set (core/models.py:78-80), so creating one is fine.
    """
    profile, _ = StreamProfile.objects.get_or_create(
        name=PROXY_PROFILE_NAME,
        defaults={"command": "", "parameters": "", "locked": True},
    )
    return profile


def add_alternate_stream(test, channel, upstream, *, order):
    """A further Stream on `channel`, on a DIFFERENT URL, so a failover can pick it.

    The different URL is load-bearing, not cosmetic: next_source's failover traversal
    rejects any candidate resolving to the URL already playing
    (apps/proxy/next_source.py:621-633), so two ChannelStreams sharing one FakeUpstream
    path make every failover answer "no alternate stream" and the test then passes or
    fails for the wrong reason. FakeUpstream's handler never inspects the request path
    (harness/upstream.py's _Handler.do_GET), so a different path on the same server is a
    genuinely different URL serving the same bytes -- and still ends in .ts, which keeps
    detect_stream_type on the 'ts' branch (utils.py:31-66) instead of forcing ffmpeg.
    """
    from apps.channels.models import ChannelStream, Stream

    first = channel.streams.order_by("channelstream__order").first()
    test.assertIsNotNone(first, "channel has no stream to copy an account from")
    base = upstream.url.rsplit("/", 1)[0]
    stream = Stream.objects.create(
        name=f"{channel.name}-alt-{order}",
        url=f"{base}/alt-{order}.ts",
        m3u_account=first.m3u_account,
        stream_profile=first.stream_profile,
        stream_hash=f"{channel.uuid}-alt-{order}",
    )
    ChannelStream.objects.create(channel=channel, stream=stream, order=order)
    return stream


def status(channel):
    """GET /proxy/relay/channels/<uuid>, through Django's own client for it.

    relay_client mints the two internal headers and dials
    DISPATCHARR_RELAY_BASE_URL, which RelayHarnessTestCase.setUp already points at the
    live server (harness/relay.py:87). None means the relay holds no metadata for the
    channel (a 404, which relay_client.get_channel:240-242 turns into None).

    The payload is built from ONE hgetall (channel_status.py:30), so state,
    ffmpeg_speed and stream_id inside one snapshot are mutually consistent -- which is
    what lets these tests assert invariants over samples instead of values at instants.
    """
    return relay_client.get_channel(str(channel.uuid))


def sample_while(test, channel, *, until=None, chunks=None, drain=None, timeout=15.0):
    """Poll the relay's own status, returning every snapshot taken, newest last.

    Exactly one stopping condition:
      until=<predicate over the snapshot dict>  stop as soon as it holds
      chunks=<int>                              stop after that many ring-buffer chunks
                                                have been read (requires drain)

    `drain` is the open _TunedStream. Reading is not incidental. The relay keeps
    producing while the test polls, and a client that never reads fills its socket
    buffer and stalls the generator thread serving it; draining also paces the loop to
    roughly real time without a fixed sleep, which is what keeps these tests off the
    clock (2a-2's plan, Keeping the suite fast).
    """
    if (until is None) == (chunks is None):
        raise ValueError("pass exactly one of until= or chunks=")
    if chunks is not None and drain is None:
        raise ValueError("chunks= counts bytes read, so it needs drain=")

    # The harness patches this down to TS_PACKET_SIZE * 10 in setUp; read it rather
    # than hardcode it, so a change there does not silently change what a test observes.
    chunk_size = TSConfig.BUFFER_CHUNK_SIZE
    snapshots = []
    read = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = status(channel)
        if info is not None:
            snapshots.append(info)
            if until is not None and until(info):
                return snapshots
        if drain is not None:
            drain.read(chunk_size)
            read += 1
            if chunks is not None and read >= chunks:
                return snapshots
        else:
            time.sleep(0.02)
    if until is not None:
        test.fail(
            f"timed out after {timeout}s; last snapshot: "
            f"{snapshots[-1] if snapshots else 'none'}"
        )
    test.fail(f"read {read} of {chunks} chunks before the {timeout}s deadline")


def read_until_end(response, *, timeout=15.0):
    """Every byte of a streaming response that is expected to END, with a deadline.

    RelayHarnessTestCase.tuned() is the wrong tool for a tune that fails: _TunedStream
    raises when the body ends early, and that ending is exactly what a connect-failure
    test is asserting. Deadline-bounded so a body that does NOT end fails the test
    rather than hanging the label -- `timeout` on the request is a socket timeout, not a
    wall-clock one.
    """
    body = b""
    deadline = time.monotonic() + timeout
    try:
        for chunk in response.iter_content(chunk_size=8192):
            body += chunk
            if time.monotonic() > deadline:
                raise AssertionError(f"response did not end within {timeout}s")
    finally:
        response.close()
    return body
```

- [ ] **Step 2: Write the failing row-28 test**

Create `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`:

```python
"""What the ffmpeg stderr reader decides: parity-matrix rows 1, 4, 5, 6 and 28.

Every stderr line these tests replay is a verbatim capture from ffmpeg 8.1.2
(harness/fixtures/ffmpeg_stderr/, CAPTURE.md). Nothing here writes a progress line, and
nothing here hardcodes a digit read off one: a capture is a timing measurement, so each
test derives what it needs and asserts the SHAPE it needs the capture to have, with a
message telling a future reader to re-derive.

Rows 6 and 28 are DEFECTS, reproduced and not fixed, per spec D5 (strict parity,
defects included). Their tests pin the wrong behaviour on purpose and say so.
"""

from unittest.mock import patch

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelState
from core.models import SystemEvent

from .harness.ffmpeg_stderr import progress_lines
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import (
    API_MAX_BUFFERING_SPEED,
    API_MIN_BUFFERING_SPEED,
    FULL_SPEED_RE,
    SPEED_RE,
    add_alternate_stream,
    corpus_elapsed,
    corpus_speeds,
    sample_while,
    set_proxy_settings,
)

# Tasks 2 and 3 add tests to this file and import nothing further: every symbol they
# need is already here.


class FfmpegStderrFailoverTests(RelayHarnessTestCase):
    def test_a_scientific_notation_speed_is_under_reported_as_its_mantissa(self):
        """PINS A DEFECT: issue #227, parity-matrix row 28. Do not "fix" this.

        input/manager.py:1064-1065's `re.search(r'speed=\\s*([0-9.]+)x?', …)` stops at
        the `e`, so a real ffmpeg line reading `speed=1.41e+03x` -- which ffmpeg 8.1.2
        emits unprompted on a truncated input -- reaches both status surfaces as 1.41, a
        roughly 1000x under-report. D5 is strict parity, defects included: the Go relay
        must under-report the same way, so this test asserts the WRONG value.

        It would fail if someone widened the regex to read the exponent, which is
        exactly the change that must not be made without also changing the Go side and
        this row.
        """
        record = progress_lines("truncation")[0]
        mantissa = float(SPEED_RE.search(record).group(1))
        actual = float(FULL_SPEED_RE.search(record).group(1))
        self.assertGreater(
            actual / mantissa,
            100,
            "the truncation capture no longer carries a scientific-notation speed=; "
            "re-derive this test against the new capture (CAPTURE.md)",
        )

        with self.stand_in(stderr_corpus="truncation", stderr_interval=0.0):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(channel) as stream:
                snapshots = sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("ffmpeg_speed") is not None,
                    drain=stream,
                )
            # Stop the channel BEFORE the stand_in context removes its temp directory.
            # The relay's main loop keeps reconnecting after the client leaves, and a
            # respawn from a deleted directory is harmless but fills the log with
            # FileNotFoundError. Every test in this PR that tunes inside a stand_in
            # block does this for the same reason.
            self.stop_channel(channel)

        reported = snapshots[-1]["ffmpeg_speed"]
        self.assertAlmostEqual(reported, round(mantissa, 3), places=3)
        self.assertLess(
            reported,
            actual / 100,
            "the relay reported the true speed; #227 appears to have been fixed, which "
            "makes this row a parity CHANGE, not a pin",
        )
```

- [ ] **Step 3: Run it**

**Do not wait for a red bar here.** This test pins a defect that already exists, so a
correct implementation passes on the first run — that is what a characterization pin
looks like, and hunting for a failure would waste the afternoon. What you are checking
is that it runs at all: the stand-in spawns, the corpus reaches the parser, and the
mantissa/exponent assertions hold against today's capture. The red-then-green cycle
applies from Task 2 onward, where the tests drive behaviour the current suite never
reaches.

```bash
docker exec -w /repo dispatcharr-testrunner-2a4 bash -lc '
export PATH=/dispatcharrpy/bin:$PATH DISPATCHARR_ENV=aio POSTGRES_HOST=/var/run/postgresql \
  POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432 \
  REDIS_HOST=localhost REDIS_PORT=6379 REDIS_DB=0 \
  CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
  DJANGO_SECRET_KEY=ci-test-secret-key DISPATCHARR_LOG_LEVEL=WARNING;
python manage.py test --keepdb apps.proxy.live_proxy.tests.test_manager_stderr_failover -v2'
```

Expected: `OK`, or a failure naming the assertion — never a hang. **If it hangs, the
cause is a `_TunedStream.read` with no data to read — check that the stand-in is actually spawning (`shutil.which("ffmpeg")` inside
the `stand_in` block) before changing anything else.**

- [ ] **Step 4: Make it pass, then run the whole label**

```bash
# same wrapper as Step 3
python manage.py test --keepdb apps.proxy.live_proxy.tests --durations 10
```
Expected: `OK`, 180 tests.

- [ ] **Step 5: Close row 28 in the parity matrix**

One `Edit`, Pin cell only. The anchor is unique to row 28:

- old: ``channel_status.py:599` | `owed: 2a-4` ``
- new: ``channel_status.py:599` | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py::test_a_scientific_notation_speed_is_under_reported_as_its_mantissa` ``

Do not touch the Source or Notes cells, do not re-pad the line, do not move the row.

- [ ] **Step 6: Run the guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a4/e2e && npx playwright test --project=guards parity-matrix
```
Expected: green, and the printed line reads `parity matrix: 28 rows — 6 pinned, 20 owed,
2 white-box-only.` **That count is only correct while this branch is the sole PR merged
on top of 2a-2** — 2a-3, 2a-5 and 2a-6 close rows in the same table, so quote it as an
expectation for this branch, never as a fact about `main`.

- [ ] **Step 7: Commit**

```bash
git add apps/proxy/live_proxy/tests/manager_support.py \
        apps/proxy/live_proxy/tests/test_manager_stderr_failover.py \
        docs/relay-parity-matrix.md
```
then, in a separate call, write the message to a file and `git commit -F` it:
`test(phase2): row 28 — a scientific-notation speed= is under-reported as its mantissa`.

---

## Task 2: The buffering trigger, and the arming delay (rows 1 and 4)

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`
- Modify: `docs/relay-parity-matrix.md` (rows 1 and 4)

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: nothing new.

- [ ] **Step 1: Write the failing row-1 test**

Append to `FfmpegStderrFailoverTests`:

```python
    def test_a_sustained_speed_below_the_threshold_fails_the_channel_over(self):
        """Row 1: speed= below buffering_speed, sustained past buffering_timeout,
        calls _try_next_stream() (input/manager.py:1122-1191).

        The lever is buffering_speed, raised to the API's maximum, exactly as
        CLAUDE.md's failover paragraph describes it ("buffering_speed above 1.0 is the
        lever"). That is what makes this affordable: the slow-trickle capture opens
        above 10.0x and every later record is below it, so the detector arms on record
        two rather than after the ~18 seconds of real ffmpeg wall clock it takes the
        cumulative average to cross 1.0 (that delay is row 4, below).

        buffering_timeout is 1 -- an integer, which is all the API stores
        (core/serializers.py:95) -- so the failover fires only after a full second of
        sustained buffering, and the event's own `duration` field proves it did.
        """
        values = corpus_speeds("slow-trickle")
        self.assertGreater(
            values[0],
            API_MAX_BUFFERING_SPEED,
            "slow-trickle no longer opens above the API's maximum buffering_speed; "
            "re-derive this test against the new capture (CAPTURE.md)",
        )
        self.assertLess(
            max(values[1:]),
            API_MAX_BUFFERING_SPEED,
            "slow-trickle no longer stays below the API's maximum after its first "
            "record; re-derive (CAPTURE.md)",
        )
        # The below-threshold run is every record after the first, replayed at 0.02s
        # apart. It has to outlast the 1-second buffering_timeout with margin: today
        # that is 75 records = 1.5s, and the failover lands around record 53 of 76. The
        # assertion is on the DURATION, not the record count, so a re-capture with a
        # different number of records is fine as long as the run is still long enough.
        self.assertGreater(
            (len(values) - 1) * 0.02,
            1.4,
            "the below-threshold tail no longer outlasts the 1s buffering_timeout this "
            "test sets; lengthen stderr_interval or re-derive (CAPTURE.md)",
        )

        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=1
        )
        with self.stand_in(stderr_corpus="slow-trickle", stderr_interval=0.02):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            alternate = add_alternate_stream(self, channel, self.upstream, order=1)

            with self.tuned(channel) as stream:
                sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
                sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("stream_id") == alternate.id,
                    drain=stream,
                )
            self.stop_channel(channel)

        buffering = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_buffering"
        )
        self.assertTrue(buffering.exists(), "buffering never armed")

        # Wait for the row, do not assume it. _try_next_stream writes STREAM_ID to the
        # metadata hash at :2125 and RETURNS; the channel_failover emit is back up in
        # _parse_ffmpeg_stats at :1156, after that return, and carries a synchronous
        # HTTP POST plus an ORM write. So the stream_id the loop above waited for lands
        # BEFORE the event row, and a bare .latest() here can raise DoesNotExist --
        # which would read as a flaky pin rather than the ordering fact it is. (Row 2's
        # stream_switch needs no such wait: it is emitted inside update_url at :1480,
        # before the same metadata write. Row 3's channel_error needs none either: it is
        # emitted at :544-551, before the finally block writes the ERROR state that ends
        # the response body the test reads to completion.)
        wait_until(
            lambda: SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_failover"
            ).exists(),
            timeout=10,
            what="the channel_failover event to reach Django",
        )
        failover = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_failover"
        ).latest("timestamp")
        self.assertEqual(failover.details.get("reason"), "buffering_timeout")
        self.assertGreater(
            failover.details.get("duration"),
            ConfigHelper.buffering_timeout(),
            "the failover fired without outlasting buffering_timeout",
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run the single test (wrapper from Task 1 Step 3, label
`apps.proxy.live_proxy.tests.test_manager_stderr_failover.FfmpegStderrFailoverTests.test_a_sustained_speed_below_the_threshold_fails_the_channel_over`).

Expected on the first run: it either passes or fails on `stream_id` never reaching the
alternate. **If it fails there, the first thing to check is `add_alternate_stream`'s
URL** — a candidate whose URL matches the one playing is rejected by
`next_source.py:621-633` and the relay logs "No alternate stream available for channel".
Read the captured log before changing a timeout.

- [ ] **Step 3: Write the failing row-4 test**

```python
    def test_the_captured_cumulative_lead_must_burn_off_before_the_detector_arms(self):
        """Row 4: speed= is ffmpeg's CUMULATIVE average since process start, so a
        front-loaded lead has to burn off before the buffering detector can arm.

        Two halves, and the first is why this row exists at all. The delay is ffmpeg's
        own behaviour and is invisible in the Python: it is visible only in a real
        capture, so the first half reads it off slow-trickle's own elapsed= field --
        the wall clock a real ffmpeg took, against an upstream held to 0.25x real time,
        before its cumulative speed first touched 1.0. That is tens of seconds, which is
        why this row can never be driven by a live ffmpeg inside a test budget.

        The second half replays that same curve at the test's own cadence, at the
        DEFAULT buffering_speed of 1.0, and asserts the invariant the delay produces:
        the relay never labels the channel buffering while the speed it is reporting is
        still at or above the threshold. Sampled, not timed -- ffmpeg_speed is written
        to Redis before the state is (input/manager.py:1206-1230 then :1190), and both
        come out of one hgetall, so a snapshot cannot show a stale pairing.
        """
        values = corpus_speeds("slow-trickle")
        default_speed = ConfigHelper.buffering_speed()
        self.assertEqual(default_speed, 1.0, "proxy_settings defaults have moved")
        crossing = next(
            (i for i, value in enumerate(values) if value < default_speed), None
        )
        self.assertIsNotNone(crossing, "slow-trickle never crosses below 1.0; re-derive")
        self.assertGreater(
            crossing, 0, "slow-trickle starts below 1.0; there is no lead to burn off"
        )
        self.assertGreater(
            corpus_elapsed("slow-trickle", crossing),
            10.0,
            "the capture's own wall clock to the crossing is now under ten seconds; "
            "re-derive -- row 4's claim is that this delay is tens of seconds",
        )
        # The invariant asserted below -- speed >= threshold implies state is not
        # buffering -- is deterministic only while the capture never climbs back over
        # the threshold after crossing it. If it did, _parse_ffmpeg_stats writes the
        # recovered speed (:1206-1230) before it resets the state (:1201), and a
        # snapshot taken in that window would show a high speed with state still
        # buffering. Today's capture is monotone below 1.0 from the crossing on; assert
        # that rather than trust it, the way row 1 asserts its own straddle.
        self.assertLess(
            max(values[crossing:]),
            default_speed,
            "the capture climbs back above the threshold after crossing it; this "
            "test's invariant is no longer race-free -- re-derive (CAPTURE.md)",
        )

        with self.stand_in(stderr_corpus="slow-trickle", stderr_interval=0.02):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(channel) as stream:
                snapshots = sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
            self.stop_channel(channel)

        leading = [
            info
            for info in snapshots
            if info.get("ffmpeg_speed") is not None
            and info["ffmpeg_speed"] >= default_speed
        ]
        self.assertTrue(
            leading, "never observed the lead at all; poll faster or pace the corpus slower"
        )
        for info in leading:
            self.assertNotEqual(
                info["state"],
                ChannelState.BUFFERING,
                f"the detector armed while speed was still {info['ffmpeg_speed']}x",
            )
```

Note that this test leaves `buffering_timeout` at its default 15, so nothing fails
over — the channel reaches `buffering` and stays there until the tune closes.

- [ ] **Step 4: Run both tests and the whole label**

Expected: `OK`, 182 tests.

- [ ] **Step 5: Close rows 1 and 4**

Two `Edit`s, Pin cells only, each anchor unique:

- row 1 — old: ``manager.py:1122-1191` | `owed: 2a-4` ``
  new: ``manager.py:1122-1191` | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py::test_a_sustained_speed_below_the_threshold_fails_the_channel_over` ``
- row 4 — old: ``input/manager.py:1064-1066`, `apps/proxy/live_proxy/input/manager.py:1122` | `owed: 2a-4` ``
  new: ``input/manager.py:1064-1066`, `apps/proxy/live_proxy/input/manager.py:1122` | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py::test_the_captured_cumulative_lead_must_burn_off_before_the_detector_arms` ``

- [ ] **Step 6: Run the guard, then commit**

Guard line expected: `28 rows — 8 pinned, 18 owed, 2 white-box-only.`
Commit message: `test(phase2): rows 1 and 4 — the buffering trigger and the arming delay it waits out`.

---

## Task 3: The snapshot, and the unbounded switch (rows 5 and 6)

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`
- Modify: `docs/relay-parity-matrix.md` (rows 5 and 6)

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: nothing new.

- [ ] **Step 1: Write the failing row-5 test**

```python
    def test_a_buffering_threshold_change_does_not_reach_a_running_channel(self):
        """Row 5: buffering_speed and buffering_timeout are snapshotted in
        StreamManager.__init__ (input/manager.py:60-61), so a proxy_settings change
        while a channel is running does not reach it.

        The second channel is what makes this falsifiable rather than vacuous. Without
        it the test would pass just as well if the settings write had silently failed,
        or if the relay ignored buffering_speed altogether. Channel B is constructed
        AFTER the change, from the same corpus and the same stand-in, and must buffer
        immediately -- so the only difference between the two channels is when their
        StreamManager was built.
        """
        values = corpus_speeds("normal")
        self.assertGreater(
            min(values),
            API_MIN_BUFFERING_SPEED,
            "normal now dips below the API's minimum buffering_speed; re-derive",
        )
        self.assertGreater(
            values[0],
            API_MAX_BUFFERING_SPEED,
            "normal no longer opens above the API's maximum buffering_speed; re-derive",
        )
        self.assertLess(
            max(values[1:]),
            API_MAX_BUFFERING_SPEED,
            "normal no longer stays below the API's maximum after its first record; "
            "re-derive",
        )

        # Nothing in the corpus can trip 0.1, so channel A must never buffer.
        set_proxy_settings(
            self, buffering_speed=API_MIN_BUFFERING_SPEED, buffering_timeout=300
        )
        with self.stand_in(
            stderr_corpus="normal", stderr_interval=0.02, stderr_loop=True
        ):
            profile = stand_in_stream_profile()
            running = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(running) as stream:
                sample_while(
                    self,
                    running,
                    until=lambda info: info.get("ffmpeg_speed") is not None,
                    drain=stream,
                )

                # Everything in the corpus now trips the threshold -- for a channel
                # built from here on.
                set_proxy_settings(self, buffering_speed=API_MAX_BUFFERING_SPEED)

                after = sample_while(self, running, chunks=24, drain=stream)

            seen = {
                info["ffmpeg_speed"]
                for info in after
                if info.get("ffmpeg_speed") is not None
            }
            self.assertGreaterEqual(
                len(seen),
                4,
                f"too few distinct speeds after the change to prove records were still "
                f"being parsed: {sorted(seen)}",
            )
            for info in after:
                self.assertNotEqual(
                    info.get("state"),
                    ChannelState.BUFFERING,
                    "the running channel picked up the new threshold",
                )
            self.assertFalse(
                SystemEvent.objects.filter(
                    channel_id=running.uuid, event_type="channel_buffering"
                ).exists()
            )

            # Same corpus, same stand-in, new StreamManager: it snapshots the NEW
            # threshold and buffers at once.
            started_after = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(started_after) as stream:
                sample_while(
                    self,
                    started_after,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
            self.stop_channel(running)
            self.stop_channel(started_after)
```

- [ ] **Step 2: Run it to verify it fails**

Expected first failure mode if anything is wrong: the second channel never reaching
`buffering`, which means the settings write did not land — but `set_proxy_settings`
asserts the read-back, so that failure would have been raised earlier and named the key.

- [ ] **Step 3: Write the failing row-6 test**

```python
    def test_a_buffering_failover_ignores_max_stream_switches(self):
        """PINS A DEFECT: issue #221, parity-matrix row 6. Do not "fix" this.

        MAX_STREAM_SWITCHES bounds the main loop (input/manager.py:388-402,
        `stream_switch_attempts <= max_stream_switches`). The buffering-timeout path
        calls _try_next_stream() from the stderr reader thread (:1134-1138) and never
        touches that counter, so the bound does not apply to it.

        Set the bound to zero and a buffering failover still happens. That is the whole
        row, and it is falsifiable in the direction that matters: if the stderr path
        were taught to consult the counter -- the natural fix for #221 -- a bound of
        zero would refuse this switch and this test would time out waiting for the
        event. D5 is strict parity, defects included, so the Go relay must ignore the
        bound the same way.

        channel_failover is emitted at exactly one site in the tree
        (input/manager.py:1156-1162), the buffering-timeout branch, so the event alone
        identifies which path made the switch.
        """
        values = corpus_speeds("normal")
        self.assertGreater(values[0], API_MAX_BUFFERING_SPEED, "re-derive; see row 5's test")
        self.assertLess(max(values[1:]), API_MAX_BUFFERING_SPEED, "re-derive")

        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=0
        )
        with patch.object(TSConfig, "MAX_STREAM_SWITCHES", 0):
            self.assertEqual(ConfigHelper.max_stream_switches(), 0)
            with self.stand_in(
                stderr_corpus="normal", stderr_interval=0.02, stderr_loop=True
            ):
                profile = stand_in_stream_profile()
                channel = self.make_channel(
                    upstream_url=self.upstream.url, profile=profile
                )
                alternate = add_alternate_stream(self, channel, self.upstream, order=1)

                with self.tuned(channel) as stream:
                    sample_while(
                        self,
                        channel,
                        until=lambda info: info.get("stream_id") == alternate.id,
                        drain=stream,
                    )
                self.stop_channel(channel)

        # Waited for, not assumed -- same ordering fact as row 1's test: the STREAM_ID
        # write at :2125 precedes the emit at :1156.
        wait_until(
            lambda: SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_failover"
            ).exists(),
            timeout=10,
            what="the channel_failover event to reach Django",
        )
        failover = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_failover"
        ).latest("timestamp")
        self.assertEqual(failover.details.get("reason"), "buffering_timeout")
```

- [ ] **Step 4: Run both, then the whole label**

Expected: `OK`, 184 tests.

- [ ] **Step 5: Close rows 5 and 6**

- row 5 — old: ``manager.py:60-61` | `owed: 2a-4` ``
  new: ``manager.py:60-61` | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py::test_a_buffering_threshold_change_does_not_reach_a_running_channel` ``
- row 6 — old: ``manager.py:1134-1138` | `owed: 2a-4` ``
  new: ``manager.py:1134-1138` | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py::test_a_buffering_failover_ignores_max_stream_switches` ``

- [ ] **Step 6: Run the guard, then commit**

Guard line expected: `28 rows — 10 pinned, 16 owed, 2 white-box-only.`
Commit message: `test(phase2): rows 5 and 6 — the threshold snapshot, and #221's unbounded buffering switch`.

---

## Task 4: The dead-air trigger (row 2)

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_manager_connection_failover.py`
- Modify: `docs/relay-parity-matrix.md` (row 2's Pin **and** Notes cells)

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: the class `ConnectionFailoverTests`, which Task 5 extends.

- [ ] **Step 1: Write the failing row-2 test**

```python
"""What the socket decides: parity-matrix rows 2 and 3, plus the raw-HTTP Proxy path.

No corpus here: these tests are about bytes stopping, not about what ffmpeg said. The
stand-in runs SILENT (stderr_corpus=None) wherever one is needed at all, so nothing the
child writes can reach the buffering detector and confuse the trigger under test.
"""

from unittest.mock import patch

import requests

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper
from core.models import SystemEvent

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import (
    API_MAX_BUFFERING_SPEED,
    add_alternate_stream,
    proxy_stream_profile,
    read_until_end,
    sample_while,
    set_proxy_settings,
)


class ConnectionFailoverTests(RelayHarnessTestCase):
    def test_dead_air_on_a_young_connection_switches_streams(self):
        """Row 2: no data for longer than the inactivity threshold, seen on three
        consecutive health checks, switches streams
        (input/manager.py:1503-1507, :1509-1560, :414-439).

        The stand-in copies a few chunks and then stays alive producing nothing
        (--dead-air-after-bytes), which is a provider that has stopped, not one that has
        disconnected -- an EOF would take the connect-failure path instead (row 3).
        Enough bytes go through first that the buffer index is non-zero, which is what
        makes _health_inactivity_threshold return CONNECTION_TIMEOUT rather than the
        60-second channel_init_grace_period (input/manager.py:1503-1507).

        HALF OF ROW 2 IS DELIBERATELY NOT PINNED. A connection stable for >= 30 seconds
        reconnects in place before it switches; `stable_time >= 30` is a bare literal at
        input/manager.py:1536 and connection_start_time is set inside
        _establish_transcode_connection, so reaching that branch costs 30 seconds of
        wall clock in a label that runs in 7 -- or reaching into the manager, which the
        composition rule forbids. Note what would fix that: apps/proxy/config.py:119
        already defines MIN_STABLE_TIME_BEFORE_RECONNECT = 30 and NOTHING READS IT
        (CLAUDE.md lists it as dead), so wiring the literal to the constant already
        named for it would make this branch patchable like every other threshold, and
        would unlock _attempt_reconnect and _wait_for_existing_processes_to_close with
        it. That is a production change and is not this PR's to make. This test drives
        the unstable branch, which is the reachable one; the matrix row's Notes cell
        says the same.
        """
        # Three unhealthy checks at 0.05s each, after 0.3s of silence. All three are
        # plain class attributes read through getattr(Config, …) / ConfigHelper.get
        # (input/manager.py:77, :1507, :1774), which is the production read path, not
        # a seam.
        #
        # CHUNK_TIMEOUT is the one that dominates, and the reason is not obvious:
        # _process_stream_data re-checks needs_stream_switch only BETWEEN fetch_chunk
        # calls, and a fetch_chunk on a dead-air pipe blocks in select() for the whole
        # chunk_timeout (:1774, :1799). At the shipped 5s the health monitor raises the
        # flag in ~0.45s and the main loop then waits out a full select before noticing
        # -- measured at 5.47s for this one test. Dropping it to 0.2 brings the test to
        # ~1.3s and changes nothing else: chunk_timeout is re-read on every fetch_chunk
        # call, not snapshotted.
        with patch.object(TSConfig, "HEALTH_CHECK_INTERVAL", 0.05), patch.object(
            TSConfig, "CONNECTION_TIMEOUT", 0.3
        ), patch.object(TSConfig, "CHUNK_TIMEOUT", 0.2):
            with self.stand_in(
                stderr_corpus=None, dead_air_after_bytes=60 * TS_PACKET_SIZE
            ):
                profile = stand_in_stream_profile()
                channel = self.make_channel(
                    upstream_url=self.upstream.url, profile=profile
                )
                alternate = add_alternate_stream(self, channel, self.upstream, order=1)

                with self.tuned(channel) as stream:
                    served = stream.read(20 * TS_PACKET_SIZE)
                    assert_ts_aligned(served)

                    # No drain: the point of this test is that no more bytes arrive.
                    sample_while(
                        self,
                        channel,
                        until=lambda info: info.get("stream_id") == alternate.id,
                        timeout=20.0,
                    )
                self.stop_channel(channel)

        self.assertTrue(
            SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="stream_switch"
            ).exists(),
            "the stream_id moved without a stream_switch event",
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run the single test. **If it times out, read the relay's log for
"Stream unhealthy for channel"** — its absence means the inactivity threshold never
tripped, and the likely cause is `buffer.index == 0`, i.e. `dead_air_after_bytes` is
smaller than `INITIAL_BEHIND_CHUNKS × TSConfig.BUFFER_CHUNK_SIZE` (4 × 1,880 = 7,520
bytes with the harness's patch). Raise the byte count; do not raise the timeout.

- [ ] **Step 3: Run the whole label**

Expected: `OK`, 185 tests.

- [ ] **Step 4: Close row 2 and amend its Notes**

One `Edit` for the Pin cell:

- old: ``manager.py:414-439` | `owed: 2a-4` ``
- new: ``manager.py:414-439` | `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::test_dead_air_on_a_young_connection_switches_streams` ``

A second `Edit`, on the same line, for the Notes cell:

- old: ``Both are gated by a 30s `action_cooldown` |``
- new: ``Both are gated by a 30s `action_cooldown`. The pin drives the unstable branch only: `stable_time >= 30` is a bare literal (`input/manager.py:1536`) that no setting compresses — `apps/proxy/config.py:119` defines `MIN_STABLE_TIME_BEFORE_RECONNECT = 30` and nothing reads it — so pinning the reconnect-first branch costs 30s of wall clock per run |``

Still one line, still unpadded.

- [ ] **Step 5: Run the guard, then commit**

Guard line expected: `28 rows — 11 pinned, 15 owed, 2 white-box-only.`
Commit message: `test(phase2): row 2 — dead air on a young connection switches streams`.

---

## Task 5: The connect-failure trigger and the raw-HTTP Proxy path (row 3)

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_manager_connection_failover.py`
- Modify: `docs/relay-parity-matrix.md` (row 3)

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: nothing new.

- [ ] **Step 1: Write the failing row-3 test**

```python
    def test_three_connect_failures_exhaust_the_source(self):
        """Row 3: MAX_RETRIES (3) consecutive connection failures exhaust the source
        (input/manager.py:50-52, :182-192, :533-538, apps/proxy/config.py:9-10).

        Driven on the PROXY stream profile, which is the same accounting on a cheaper
        path: _establish_http_connection hands back a pipe immediately, HTTPStreamReader
        gets the upstream's 404 and closes the write end, and fetch_chunk's EOF branch
        ends the attempt exactly as a dead child would (input/manager.py:1826-1831).
        Three attempts, the exponential backoff between them, then url_failed, the
        channel_error event, and -- with no alternate stream -- the ERROR state, which
        the client sees as an `Error:` TS packet rather than a hang
        (output/ts/generator.py:229, utils.py:96-98).

        The window-reset half of this row -- the counter resetting once a gap exceeds
        RETRY_WINDOW_SECONDS -- is already pinned by
        test_failover_retry_window.py::test_counter_resets_after_idle_period, which the
        matrix row cites alongside this test. Reproducing it here would mean compressing
        the window below the backoff so the channel could never exhaust at all, i.e.
        asserting that a loop does not terminate.

        MAX_RETRIES is patchable, and is deliberately NOT patched: the row names the
        value 3, so the test pays the 0.75s of backoff rather than change the number
        under test.
        """
        self.assertEqual(ConfigHelper.max_retries(), 3)
        self.upstream.faults.arm("not-found")

        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        response = requests.get(
            f"{self.live_server_url}/proxy/ts/stream/{channel.uuid}",
            stream=True,
            timeout=30,
        )
        self.assertEqual(response.status_code, 200)
        body = read_until_end(response, timeout=20.0)

        self.assertIn(b"Error:", body, "the client was not told why the tune failed")
        self.assertGreaterEqual(
            self.upstream.request_count,
            3,
            "fewer than MAX_RETRIES connection attempts reached the upstream",
        )

        error = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_error"
        ).latest("timestamp")
        self.assertEqual(error.details.get("error_type"), "connection_failed")
        self.assertEqual(error.details.get("attempts"), ConfigHelper.max_retries())
```

- [ ] **Step 2: Run it to verify it fails**

**If `read_until_end` raises "response did not end within 20s"**, the generator did not
see the ERROR state. Read the relay log: the `finally` block at `input/manager.py:644-690`
only writes ERROR when this worker still owns the channel or nobody does. Do not raise
the timeout to make it pass.

- [ ] **Step 3: Write the Proxy-path streaming test**

```python
    def test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats(self):
        """The raw-HTTP Proxy path end to end -- no subprocess anywhere.

        Closes no matrix row, and is here for two reasons. It is the only test in stage
        2a that exercises input/http_streamer.py at all (101 statements, 0% on this
        branch), together with _establish_http_connection and _close_socket's HTTP
        branch -- roughly 143 statements of input/manager.py the spec's 2a-4 row calls
        out as needing "only a socket".

        And the negative it asserts is real, externally-visible parity: the buffering
        detector is ffmpeg-exclusive. A Proxy-profile channel has no stderr, so
        _parse_ffmpeg_stats never runs, ffmpeg_speed never appears on the status, and
        buffering_speed/buffering_timeout are silently inert -- which is exactly what
        CLAUDE.md's failover paragraph records and what nothing in the UI says. The
        threshold is set to the API maximum here so the assertion is a real negative:
        on the ffmpeg profile that same setting buffers on the second record (Task 3's
        row-6 test), and here it does nothing at all.

        The window is measured in ring-buffer chunks read, not in seconds, so it cannot
        become a fixed sleep.
        """
        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=0
        )
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        with self.tuned(channel) as stream:
            served = stream.read(20 * TS_PACKET_SIZE)
            assert_ts_aligned(served)
            snapshots = sample_while(self, channel, chunks=40, drain=stream)

        self.assertTrue(snapshots)
        for info in snapshots:
            self.assertNotIn(
                "ffmpeg_speed",
                info,
                "the Proxy profile reported an ffmpeg speed; there is no ffmpeg",
            )
            self.assertNotEqual(info.get("state"), "buffering")
        self.assertFalse(
            SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_buffering"
            ).exists()
        )
```

- [ ] **Step 4: Run both, then the whole label**

Expected: `OK`, 187 tests.

- [ ] **Step 5: Close row 3, with two references**

- old: ``config.py:9-10` | `owed: 2a-4` ``
- new: ``config.py:9-10` | `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::test_three_connect_failures_exhaust_the_source`, `apps/proxy/live_proxy/tests/test_failover_retry_window.py::test_counter_resets_after_idle_period` ``

Two references in one Pin cell is the shape row 10 already uses; the guard resolves each
independently (`e2e/tests/guards/parity-matrix.ts:437`, `:490-493`).

- [ ] **Step 6: Run the guard, then commit**

Guard line expected: `28 rows — 12 pinned, 14 owed, 2 white-box-only.` **No row anywhere
in the table still carries an `owed: 2a-4` Pin cell** — check the cell form, not the bare
string:

```bash
grep -c '| `owed: 2a-4` |' docs/relay-parity-matrix.md   # expected 0
grep -c 'owed: 2a-4' docs/relay-parity-matrix.md         # expected 1, NOT 0
```

The second returns 1 forever: line 118 is the Format section's own prose, "``owed:
2a-4`` and `owed: 2a-4` both parse", explaining the syntax. It is documentation, not a
row, and deleting it to make a grep tidy would remove the explanation of the marker this
whole PR removes.

Commit message: `test(phase2): row 3 — three connect failures exhaust the source, on the Proxy path`.

---

## Task 6: The measurement, the ledger, and the shuffle run

**Files:**
- Modify: `metrics/curated/defects.yml`
- No test or source file changes.

**Interfaces:**
- Consumes: the two test files, by path, for the ledger's `test:` field.
- Produces: the numbers the PR description carries.

- [ ] **Step 1: Measure the coverage delta, both halves in one session**

The gate is **a measured increase on `input/manager.py`**, never an exact statement
count, and **the delta is quoted as a range across at least three runs of each side, not
as a single figure.** The run-to-run spread is not a constant: it is **2 statements on
the base tree, ~10 once 2a-3's tests are present, and ~51 once the fMP4 and Output
Profile managers are exercised** — those start three background loops each, and whether a
loop ticks inside a teardown window is not controllable from a test. Depending on merge
order this PR's measurement may be taken on a tree near the loaded end, where a
single-run delta of, say, 60 statements carries a ±51 band and means very little on its
own. Three runs a side is what turns it into a claim.

Measure the baseline and the new number **back to back, in the same container, in the
same session** — a figure quoted from § F1 of this plan is a different session's number
and is not a valid baseline.

`$SCRATCH` below is **your session's scratchpad directory** (the harness names it in your
system prompt) — not `/tmp`, and not anywhere inside the repository, which is mounted
read-only. A container bind-mounts one tree read-only at `/repo`, so the baseline needs a
**second worktree and a second container** — you cannot check the branch point out underneath the
one you are working in:

```bash
git -C /Users/dion/git/Dispatcharr worktree add "$SCRATCH/2a4-baseline" 2a826e07
CLAUDE_HOOK_REPO_ROOT="$SCRATCH/2a4-baseline" \
DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a4-base \
DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a4-base \
  /Users/dion/git/Dispatcharr/.worktrees/phase2-2a4/.claude/hooks/start-test-container.sh
```

Then run `bash scripts/coverage_live_path.sh` inside each container in turn — the
baseline one and `dispatcharr-testrunner-2a4` — back to back, with the same image, in
the same session. (`$SCRATCH/2a4-baseline/.git` is a file pointing at the main repository,
which the baseline container does not mount; nothing the test run needs reads it.)

Record, for each of the three runs a side: `TOTAL` statements (must be **7978** every
time — the denominator is the check and does not vary), `TOTAL` `Miss`, and the `Miss`
column for `apps/proxy/live_proxy/input/manager.py` and
`apps/proxy/live_proxy/input/http_streamer.py`. Report each as `min-max`, and report the
delta as the range it actually is.

**Check the tracer core before you start (§ Rulings (b)).** `sysmon` has been adopted and
2a-2 owns the change. If `scripts/coverage_live_path.sh` or its rcfile now selects it,
both halves of this measurement must be taken under it — never one half under each; the
two cores differ by ~102 statements on this denominator, four times the run-to-run
spread. Since both halves are taken back to back here, this costs nothing but reading the
script first. Say in the PR description which core produced the numbers.

**Expected direction and rough size, not a target:** `input/manager.py` from 498 missed
down by somewhere in the region of 60-120; **`http_streamer.py` from 101 missed to
around 27** — measured, not guessed: driving `HTTPStreamReader` through the two call
shapes this PR's Proxy tests use (`input/manager.py:1259-1266`'s construct-and-`start()`,
and `:1685`'s `stop()`), on both the happy path and the 404 path, executes **74 of its
101 statements**. That module is a **separate coverage entry from `input/manager.py`**
and today reports `executed_lines: 0`, so its statements are disjoint from the 474 this
PR's other work moves — they add, they do not double-count. **Do not treat a smaller movement as a failed task
without first checking § F2** — the statements immediately following every
`gevent.sleep()` in the paths these tests drive are executed but not recorded, and no
test can turn them green under the committed rcfile.

Tear the baseline down when done:

```bash
docker rm -f dispatcharr-testrunner-2a4-base
docker volume rm dispatcharr-hookdb-2a4-base
git -C /Users/dion/git/Dispatcharr worktree remove "$SCRATCH/2a4-baseline"
```

- [ ] **Step 2: Measure the time cost**

```bash
python manage.py test --keepdb apps.proxy.live_proxy.tests --durations 15
```
Record the total and the eight new tests' individual durations. Compare against § F1's
**179 tests in 7.006 s** and § F9's expected **≈8.5 s** added. **Check `--durations`
before concluding any test is inherently slow** — three times in this programme the cost
has been a library default or an unpatched timeout rather than the work, row 2's
`CHUNK_TIMEOUT` being the third. State the number in the PR description; there is no
ceiling to meet, only a 45 s reconsideration trigger on this label (§ Rulings (a)).

- [ ] **Step 3: Update the defect ledger**

Three edits to `metrics/curated/defects.yml`, each one line:

1. `max-stream-switches-unbounded` (#221): `status: open` → `status: pinned`,
   `test: null` → `test: apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`,
   `status_changed: 2026-08-22` → `status_changed: 2026-09-10`.
   `open` → `pinned` is an allowed transition (`metrics/build/curated.py:50-51`), and
   `pinned` requires both `issue` and an existing `test` path (`:314-315`).
2. A new entry for **#227**, which 2a-2 filed as an issue and added to the parity matrix
   but **not** to this ledger (§ Findings F4), appended in the same one-line style:

```yaml
- {id: ffmpeg-speed-scientific-notation, title: "ffmpeg_speed is parsed with [0-9.]+, which stops at the e of a scientific-notation speed=, so a real speed=1.41e+03x is reported as 1.41", area: correctness, severity: low, status: pinned, source: null, issue: 227, test: apps/proxy/live_proxy/tests/test_manager_stderr_failover.py, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
```

3. A new entry for **#232**, the cache-invalidation defect this PR's own read-back
   assertion found (§ Findings F6). `status: open`, not `pinned`: this PR works around
   it in `set_proxy_settings` rather than pinning it, and `open` needs only an `issue`
   (`metrics/build/curated.py:312-313`):

```yaml
- {id: proxy-settings-cache-cleared-on-wrong-class, title: "CoreSettings' post_save receiver calls BaseConfig.clear_proxy_settings_cache(), which never clears the TSConfig attribute every relay reader populates, so a proxy_settings change is invisible to every process until the 10-second TTL expires", area: correctness, severity: medium, status: open, source: null, issue: 232, test: null, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
```

- [ ] **Step 4: Validate the ledger**

**On the host, not in the container** — the build shells out to `git`, which the test
image does not carry (`FileNotFoundError: [Errno 2] No such file or directory: 'git'`):

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a4 && uv run python -m metrics.build --validate-only
```
Expected: `ok: 46 metrics, 32 milestones, 30 defects`. The same command prints
`… 28 defects` on this branch today (verified), so the count moving by exactly two —
#227 and #232 — is the check.
The `metrics/**` `PostToolUse` hook runs `scripts/run_metrics_tests.sh` and
`python -m metrics.build --validate-only` on the edit itself; a green hook is not a
substitute for reading the count.

- [ ] **Step 5: Run both labels in default order and under shuffle**

```bash
python manage.py test --keepdb apps.proxy.live_proxy.tests
python manage.py test --keepdb apps.channels.tests
python manage.py test --keepdb --shuffle 12345 apps.proxy.live_proxy.tests
```
All three green. **The shuffle run is the one that catches § F7's leak**: a
`proxy_settings` cleanup that does not fire leaves a later test with this PR's
thresholds, and shuffling is what puts an unrelated test after one of these.

- [ ] **Step 6: Run the parity guard one last time and commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a4/e2e && npx playwright test --project=guards
```
Expected: every guard test green, `28 rows — 12 pinned, 14 owed, 2 white-box-only.`

Commit message: `chore(phase2): 2a-4's defect ledger entries and the measured numbers`.

- [ ] **Step 7: Write the PR description**

It must carry, in this order:

1. The coverage numbers from Step 1, before and after, per file, with the denominator
   7,978 shown as the shape check, **which tracer core produced them**, and the sentence
   that the gate is a **measured increase**, not a count.
2. The time cost from Step 2, against the 7.006 s baseline and the ≈8.5 s expectation.
   State plainly that all eight tests were built, that the ≤15 s ceiling is withdrawn in
   favour of a 45 s reconsideration trigger on this label (§ Rulings (a)), and that
   § F9's drop order was recorded and **not taken**.
3. The six findings in § Findings below, each in a sentence or two — **F6 (#232) first**, being the only one that is a live production defect rather than a record.
4. **F5's recommendation to 2a-7, spelled out**: the buffering detector is inert on the
   Proxy and Redirect profiles; it is a real externally-observable behaviour the Go relay
   must reproduce; it has no matrix row because adding one means bumping
   `HIGHEST_ROW_ID` against four PRs in flight; 2a-7 should add it citing
   `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats`.
5. The seven rows closed, by number, with their test symbols, and the note that row 2's
   Notes cell now records which half of that row is pinned.
6. The three defect-ledger changes.

---

## Findings against the spec and the harness, to carry into the PR description

Six, all verified on this branch, none of which this PR fixes — every one of them lives
in a file this PR is fenced out of. **F6 is the one that changes production behaviour**,
and it is the only one this PR had to work around rather than merely record.

**F1 — stage 2a's ≤15 s test-time ceiling is not reachable at four PRs.** Measured
(§ F1): one `RelayHarnessTestCase` tune costs ~0.7 s before it waits for anything, the
label is at 7.006 s, and 2a-2 already spent ~3.96 s of the 15. This PR's eight tests are
each a real tune plus the real time a timeout takes; the predicted total is 9-11 s, which
consumes the remainder and leaves 2a-3, 2a-5 and 2a-6 with nothing. **The single largest
lever is not in any of these PRs**: `RelayHarnessTestCase` is a `TransactionTestCase`,
so every test flushes every table, and `available_apps` on the base class would narrow
that flush — 2a-2's own plan names it and declines to reach for it unmeasured. **Resolved
(§ Rulings (a)): the ceiling is withdrawn and replaced by per-PR measurement with a
reconsideration trigger at 45 s on this label; all eight tests are built;
`available_apps` goes to 2a-2, which owns the base class.** Cutting tests was rejected —
in the PR whose purpose is coverage, both available cuts are worse than a slower commit
hook. With the `CHUNK_TIMEOUT` lever in row 2, the measured cost is **≈8.5 s**, not the
9-11 s this finding first predicted.

**F2 — the Gate 2 measurement systematically under-counts, and the tracer is part of the
measurement shape.** Statements executing after a `gevent.sleep()` are not recorded by
coverage's default C tracer (§ F2, reduced case included). `COVERAGE_CORE=sysmon` records
them: measured on this branch, the same three labels give **3,114 missed instead of
3,216** — `+1.3` percentage points of the 80% gate, free, with `input/manager.py` at 474
instead of 498, `server.py` at 797 instead of 845 and `channel_service.py` at 169 instead
of 200, and all three labels still green. `concurrency = gevent` is the *wrong* fix and
was measured as such (3,877 missed — the suite is not monkey-patched, so gevent mode
stops tracing the relay's real OS threads), which is worth stating on its own: it rules
out the remedy most readers would try first, for a measured reason. **And
`scripts/coverage_live_path.sh`'s shape guard does not stamp the tracer core**, so a
floor written under one core and compared under the other is un-meetable in exactly the
way the guard exists to prevent — the worse half of this finding.

**Resolved (§ Rulings (b)): `sysmon` is adopted and the shape stamp gains the tracer
core, both in 2a-2**, conditional on 2a-2 verifying on a concrete example that the extra
credit is for genuinely executed lines — a tracer that *over*-credits an 80% gate would
be worse than one that under-counts, so it is checked once rather than assumed. The four
coverage PRs re-take their baselines under it.

**F3 — `scripts/coverage_live_path.sh:22-25` is stale.** It says "Within this shape the
measurement is exactly reproducible … so this script has no tolerance and needs none."
The spec withdrew that ruling at `0c7e19a4` ("the round-6 ruling that the ratchet needs
*no tolerance at all* is withdrawn"), on evidence gathered after that comment was
written. The comment is the first thing 2a-7's implementer will read.

**F4 — issue #227 is in the parity matrix but not in the defect ledger.** 2a-2 added the
#226 entry and row 28 in the same PR, and its Done criteria pinned the ledger at 28
defects, so #227 was filed and then dropped. This PR adds it (Task 6 Step 3). Worth
noting because the ledger is the input to a published dashboard: a defect that exists in
the matrix and not in the ledger is invisible there.

**F6 — `CoreSettings`' `post_save` receiver clears the proxy-settings cache on the wrong
class, so a `proxy_settings` change reaches no relay reader until the 10-second TTL
expires ([#232]).** `get_proxy_settings` is a classmethod caching on `cls`
(`apps/proxy/config.py:32-51`); every relay reader binds the **subclass**
(`from apps.proxy.config import TSConfig as Config`, `config_helper.py:5`,
`input/manager.py:11`), so the cached dict lands on `TSConfig` as a shadowing class
attribute. The receiver calls `BaseConfig.clear_proxy_settings_cache()`
(`core/models.py:360-361`), which sets `BaseConfig`'s own attribute and leaves the
shadow. **`CLAUDE.md` § Known defects overstates the position** — it says "saving clears
the cache only in the worker that handled the write", but the write clears *no* worker's
`TSConfig` cache, including its own; the 10-second `_proxy_settings_cache_ttl` is the
sole expiry, in every process. Found by this PR's `set_proxy_settings` read-back
assertion, which is the reason that assertion exists. `set_proxy_settings` works around
it with one explicit `TSConfig.clear_proxy_settings_cache()` call; **the production fix
is #232 and is not in this PR's scope.** The `CLAUDE.md` sentence is wrong today and
should be corrected wherever that file is next legitimately edited — not here, it is out
of bounds.

**F5 — a real parity behaviour has no row: the buffering detector is inert on the Proxy
and Redirect profiles.** `_parse_ffmpeg_stats` is the only writer of `ffmpeg_speed` and
the only caller of the buffering check, and it runs only from the stderr reader, which
only a transcode profile has. So `buffering_speed` and `buffering_timeout` are silently
ignored for two of the three Stream Profile architectures — externally observable
(`ffmpeg_speed` never appears on the status), recorded in `CLAUDE.md`, and something the
Go relay must reproduce. Task 5's Proxy-path test asserts it, but it closes no row: adding
one means bumping `HIGHEST_ROW_ID`, and 2a-3, 2a-5 and 2a-6 would all conflict on that
constant. **Accepted as a row for 2a-7** (§ Rulings), which lands after all four and can bump the
constant once, citing
`test_manager_connection_failover.py::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats`.
**The PR description must name that test and the reason for the deferral explicitly**, so
2a-7's planner inherits the recommendation instead of rediscovering the behaviour.

---

## Verification commands

Every "run the tests" step means, from
`/Users/dion/git/Dispatcharr/.worktrees/phase2-2a4`:

```bash
docker exec -w /repo dispatcharr-testrunner-2a4 bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH DISPATCHARR_ENV=aio POSTGRES_HOST=/var/run/postgresql \
     POSTGRES_DB=dispatcharr POSTGRES_USER=dispatch POSTGRES_PASSWORD=secret POSTGRES_PORT=5432 \
     REDIS_HOST=localhost REDIS_PORT=6379 REDIS_DB=0 \
     CELERY_BROKER_URL=redis://localhost:6379/0 CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
     DJANGO_SECRET_KEY=ci-test-secret-key DISPATCHARR_LOG_LEVEL=WARNING; \
   python manage.py test --keepdb <label> -v2'
```

**Container isolation is mandatory** — three sibling PRs share the default container by
name. Start your own once, and remove it and its volume when the PR is done:

```bash
DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a4 \
DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a4 \
  .claude/hooks/start-test-container.sh
# ... and at the end:
docker rm -f dispatcharr-testrunner-2a4 && docker volume rm dispatcharr-hookdb-2a4
```

The image override is required: the script's default is upstream's image, which carries
neither `coverage` nor `hypothesis` (issue #228).

Task 6 starts a **second** container, `dispatcharr-testrunner-2a4-base`, against a
throwaway worktree at the branch point, because a container bind-mounts one tree and the
coverage baseline has to come from a different one. Both are named, both are yours, and
both are removed at the end. **Never restart or re-mount the shared
`dispatcharr-testrunner`** — three sibling PRs are using it.

The repository is bind-mounted **read-only** at `/repo`, so everything these tests write
goes under `/tmp` — which `StandInBin` already does with `tempfile.mkdtemp()`.

Guard: `cd e2e && npx playwright test --project=guards parity-matrix` (no container
needed).

**If Docker is down the hook says so and exits 0. Then say the tests did not run — do
not describe the work as verified.**

---

## Done criteria

- [ ] `docs/relay-parity-matrix.md` contains **no** `owed: 2a-4` — rows 1, 2, 3, 4, 5, 6
      and 28 each carry a test reference the guard resolves.
- [ ] `cd e2e && npx playwright test --project=guards` is green and prints
      `parity matrix: 28 rows — 12 pinned, 14 owed, 2 white-box-only.` (correct for this
      branch alone; the counts move as the sibling PRs merge).
- [ ] `HIGHEST_ROW_ID` is still 28 and `e2e/tests/guards/` is untouched.
- [ ] `apps.proxy.live_proxy.tests` and `apps.channels.tests` are green in default order,
      and `apps.proxy.live_proxy.tests` is green under `--shuffle 12345`.
- [ ] `scripts/coverage_live_path.sh` reports `statements 7978` and a **strictly lower**
      `Miss` for `apps/proxy/live_proxy/input/manager.py` than the same-session baseline
      at `2a826e07`.
- [ ] `uv run python -m metrics.build --validate-only` prints `ok: 46 metrics,
      32 milestones, 30 defects`.
- [ ] Only these files changed: `apps/proxy/live_proxy/tests/manager_support.py`,
      `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py`,
      `apps/proxy/live_proxy/tests/test_manager_connection_failover.py`,
      `docs/relay-parity-matrix.md`, `metrics/curated/defects.yml`, and this plan.
      In particular **no** production module, **no** file under
      `apps/proxy/live_proxy/tests/harness/`, **no** `scripts/coverage_live_path.*`,
      **no** `CLAUDE.md`, **no** workflow.
- [ ] No test asserts a digit read off a capture; every corpus relationship a test needs
      is asserted with a re-derive message.
- [ ] The two defect-pinning tests (rows 6 and 28) say in their docstrings that they pin
      the wrong behaviour on purpose, and name the issue.
- [ ] All eight tests exist. § F9's drop order was **not** taken (§ Rulings (a)).
- [ ] The PR description carries the six items of Task 6 Step 7, including the six
      findings above, F5's spelled-out recommendation to 2a-7, and which tracer core
      produced the coverage numbers.
- [ ] `dispatcharr-testrunner-2a4`, `dispatcharr-hookdb-2a4` and, if Task 6 started them,
      `dispatcharr-testrunner-2a4-base` / `dispatcharr-hookdb-2a4-base` are removed, along
      with the `$SCRATCH/2a4-baseline` worktree.
- [ ] Nothing is pushed and no PR is opened.
