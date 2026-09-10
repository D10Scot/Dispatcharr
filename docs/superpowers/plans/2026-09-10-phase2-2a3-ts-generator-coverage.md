# Phase 2 PR 2a-3 — TS generator and channel-service coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin parity-matrix rows 7, 8, 9, 10 and 13 with harness tests that drive the relay over HTTP against real dependencies, and raise measured statement coverage on `apps/proxy/live_proxy/output/ts/generator.py` and `apps/proxy/live_proxy/services/channel_service.py`.

**Architecture:** Five new `RelayHarnessTestCase` tests in two modules, plus one new harness module holding the helpers that drive the *control* surfaces (`/proxy/ts/status/`, `/change_stream/`, `/stop/`, `/stop_client/`) as an admin over real HTTP, and that open a tune carrying the headers nginx would have set. No production code changes. No existing harness *code* file is edited — every helper 2a-3 needs lives in a new file, so the four parallel coverage PRs cannot collide there.

**Tech Stack:** Django 6 `LiveServerTestCase`, `requests`, real Redis, real PostgreSQL, the 2a-2 subprocess harness (`apps/proxy/live_proxy/tests/harness/`), `scripts/coverage_live_path.sh`, the Playwright `guards` project.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (in the `phase2-spec` worktree at `0c7e19a4`; PR #225). Read § Stage 2a — Gate 1, Gate 2, § The subprocess harness (especially its **Composition rule**), and the `2a-3` row of § The seven PRs.

**Branch:** `migration/phase2a-ts-generator-coverage`, stacked on `migration/phase2a-subprocess-harness` at **`27c9e79c`**, that branch's head.

---

## Global Constraints

- **The composition rule is not negotiable** (spec § The subprocess harness): drive the relay through its **HTTP surface** against **real dependencies** — the fake upstream, real Redis, the real spawned stand-in — **never against mocks of `server.py`'s or `input/manager.py`'s internals**. Ask of every assertion whether it still means something when the implementation underneath is Go. `unittest.mock.patch.object` on a **configuration class attribute** is not a mock of an internal: it is the production lever (`ConfigHelper.get` is `getattr(TSConfig, name, default)`, `apps/proxy/live_proxy/config_helper.py:16`), and the 2a-2 harness already uses it for `BUFFER_CHUNK_SIZE` (`harness/relay.py:117`).
- **These are characterization tests, so the TDD cycle inverts.** There is no red step from missing production code: the behaviour already exists. The discipline that replaces it is stated per test — *predict what the code does, run it, and if the prediction is wrong fix the prediction, never the code* — plus, where noted, an explicit **break check**: temporarily change one thing, confirm the test fails, revert.
- **`TransactionTestCase` flushes every table after each test, including migration-seeded rows** (`harness/README.md` § Two traps). A harness test creates every row it needs. `stand_in_stream_profile()` and `self.make_channel()` already do this; `ControlMixin.admin_headers()` (Task 2) does it for the admin user.
- **A `proxy_settings` write has TWO caches behind it and leaks for the rest of the process if either survives.** `TSConfig._proxy_settings_cache` is process-local with a 10-second TTL (`apps/proxy/config.py:22-24`), and `CoreSettings` keeps the group in **Redis for 300 seconds** (`core/models.py:220-222`). `TransactionTestCase` flushes with TRUNCATE, which fires no `post_delete`, so the Redis entry outlives the row it came from and the process-local copy is refilled from it — measured: the DB row was empty and the next test class still read the override. It is not "the next ten seconds", it is until something invalidates it. `ControlMixin.set_proxy_setting()` (Task 2) clears both, on write and on cleanup, and **`CoreSettings.invalidate_group_cache` alone is not enough** — see its docstring and § Findings.
- **No hard-coded measurement may appear in an assertion** (spec's ratchet paragraph; the programme's defect class 9). Every threshold in these tests is derived at run time from `NOMINAL_BYTE_RATE`, `FakeUpstream.rate`, `TSConfig.BUFFER_CHUNK_SIZE`, `TS_PACKET_SIZE` or a patched config value.
- **Matrix editing rules** (`docs/relay-parity-matrix.md`, the HTML comment above the table): one row is one line; cells are never padded; no stored counts; **do not run a Markdown formatter over the file**; the table ends at `<!-- end of matrix -->`. This PR **adds no row**, so `HIGHEST_ROW_ID` in `e2e/tests/guards/parity-matrix.ts` stays at **28** and that file is not touched.
- **`scripts/coverage_live_path.sh` is the only sanctioned measurement** and it runs per label. Quote **per-file** numbers from the report, never the global `missing`. **The tracer core is part of the measurement shape**: since `9c865538` the script sets `export COVERAGE_CORE=sysmon` itself and stamps `per-label/v2-${COVERAGE_CORE}`, because coverage's default C tracer drops every statement executing immediately after a greenlet switch. Do **not** set the core yourself and do **not** compare a number taken under one core with one taken under another — the shape guard refuses the mix, and where it cannot see the mix (two numbers in a PR description) it is the arithmetic that silently breaks. **Name the core beside every number you report.**
- **Container isolation.** The shared `dispatcharr-testrunner` is used by other agents. Start your own:
  `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a3 DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a3 .claude/hooks/start-test-container.sh`
  The image override is required — the script's default is upstream's image, which lacks `coverage` and `hypothesis` (issue #228). Remove the container and volume when you finish.
- **`manage.py test` is not gevent-monkey-patched**, so the relay's workers are real pre-emptive OS threads under test (`harness/README.md` § Two environment facts).

### An illustrative measurement — not a target

**The gate is relative, and the figures below are an illustration of it, not a number to reconcile against.** Take your own baseline in your own session, under the core your `scripts/coverage_live_path.sh` sets, and require **strictly fewer missed statements** on the two named files than that baseline. An absolute figure written here is wrong the moment anything upstream moves, and during this stage it has moved three times: the harness landed, the tracer core changed, and 2a-6's probes changed what the pool looks like.

One same-session pair, for shape only. Measured in `dispatcharr-testrunner-2a3` on 2026-09-10 against **`27c9e79c`**, all three labels combined, **tracer core `sysmon`** (the core `scripts/coverage_live_path.sh` sets for itself since `9c865538`), three runs of each configuration:

| File | Baseline (3 runs) | With this PR's five tests (3 runs) | Direction |
|---|---|---|---|
| `apps/proxy/live_proxy/output/ts/generator.py` (377 stmts) | 119 / 119 / 119 | **95 / 96 / 96** | **down** |
| `apps/proxy/live_proxy/services/channel_service.py` (500 stmts) | 169 / 169 / 169 | **145 / 145 / 145** | **down** |
| `apps/proxy/live_proxy/input/buffer.py` (248 stmts) | 99 / 100 / 99 | 87 / 85 / 87 | down |
| `apps/proxy/live_proxy/client_manager.py` (262 stmts) | 92 / 92 / 92 | 52 / 52 / 52 | down |
| whole denominator | 3,116 / 3,117 / 3,112 | 2,973 / 2,966 / 2,967 | down |

The denominator was 7,978 in all six runs. **That is the figure to check** — it is a property of the rcfile and moves only if the module list does. The `missing` column is a sample from a band, not a constant.

**Why the relative form is not pedantry, in one number from this very table.** Under the previous C tracer the same two configurations gave `channel_service.py` **200 → 145**, a delta of −55. Under `sysmon` they give **169 → 145**, a delta of −24. The *after* value is identical by coincidence; the baseline is not, because sysmon credits 31 statements to the existing suite that the C tracer was dropping after greenlet switches. An executor holding "−55" as a target would have concluded this PR had regressed.

Adopting `sysmon` widened the observed band rather than narrowing it, which is expected: the C tracer's systematic loss after a greenlet switch was also flattening the difference between "the relay's background housekeeping fired on this run" and "it did not". **The denominator, 7,978, is the number to check; a differing `missing` is a question, not a defect.**

**Test-time cost, measured: +10.9 s on `apps.proxy.live_proxy.tests`** — 179 tests in 6.04 / 6.09 / 6.62 s becomes 184 tests in 17.16 / 17.28 / 17.88 s. Per-test method bodies (`--durations`) sum to ≈ 6.0 s; the remaining ≈ 2.6 s is `LiveServerTestCase` setUp plus `RelayHarnessTestCase`'s per-channel cleanup, which `--durations` does not count. **This exceeds an even share of the stage's ≤ 15 s ceiling** (2a-2 spent ≈ 3.96 s, leaving ≈ 11 s for four PRs), and **the ceiling was subsequently withdrawn**. About 2.2 s of the total buys the ghost test its load-bearing premise — see Task 3 — and that trade was made deliberately: a pin that pins the wrong thing is worth less than the seconds it saves. Each row needs its own channel bring-up and a bring-up costs ≈ 0.6 s before the row's behaviour is reachable at all, so ≈ 7 s is the floor for five rows however they are arranged.

---

## File structure

Create:

| Path | Responsibility |
|---|---|
| `apps/proxy/live_proxy/tests/harness/control.py` | Drive the relay's **control** surfaces over real HTTP: an admin principal, the four admin routes, `proxy_settings` writes through the production lever, and `open_tune()` for a tune that needs custom headers or a non-200. **New file, so the four parallel 2a coverage PRs cannot conflict here.** |
| `apps/proxy/live_proxy/tests/test_relay_client_stream.py` | What a client receives and what the client set does: matrix rows **9**, **10** and **13**, plus `channel_service.stop_client`/`stop_channel`. |
| `apps/proxy/live_proxy/tests/test_relay_stream_switch.py` | What a stream switch and a late join do: matrix rows **7** and **8**, plus `channel_service.change_stream_url`'s owner branch. |

Modify:

| Path | Change |
|---|---|
| `docs/relay-parity-matrix.md` | Five row lines: 7, 8, 9 and 13 lose `owed: 2a-3`; row 10 gains a third pin. One line each, no other line touched. |
| `apps/proxy/live_proxy/tests/harness/README.md` | One new section documenting `control.py`, appended after § Writing a test. |
| `CLAUDE.md` | § Testing, line 138: "Exactly one test file talks to a real Redis; the lease and ring buffer never meet real Redis semantics" is false from this PR onward and was already half-false after 2a-2. Corrected in place. |

Not touched, deliberately:

- **Any production file.** 2a-3 adds tests; the spec's open question about extracting a spawn seam was settled in 2a-2 as *no production change*, and nothing here reopens it.
- **`e2e/tests/guards/parity-matrix.ts`** — no row is added or removed, so `HIGHEST_ROW_ID` (28), `PRS` and `WHITE_BOX_ONLY` are all unchanged. `GATE_1_CLOSED` stays `false`: seventeen rows are still owed after this PR.
- **Any production file, including `input/buffer.py`** — Task 4 Step 4 edits it temporarily for a break check and restores it; nothing is committed.
- **Any existing file under `apps/proxy/live_proxy/tests/harness/` except `README.md`** — in particular `relay.py`, whose `tuned()`/`tune()` gain no parameters. `control.py`'s `open_tune()` imports `_TunedStream` from `.relay` (same package) instead. This is deliberate contention avoidance: 2a-4, 2a-5 and 2a-6 develop in parallel against the same harness.
- **`e2e/COVERAGE.md`** — no Playwright test is added or changed; the `guards` project's test count is unchanged.
- **`metrics/curated/**`** — this PR closes no ledger issue, adds no `test.fail()` pin, merges no goal and ticks no Done log, so `docs/agents/metrics.md`'s rule does not fire.
- **`scripts/coverage_live_path.sh` / `.coveragerc`** — 2a-7 owns the floor and the tolerance, including the stale header comment named in Global Constraints.
- **`CLAUDE.md`'s "2,212 backend tests" count at line 132** — already stale before this PR (2a-2 added tests without bumping it), and correcting it honestly needs a sixteen-label count this PR does not run. Left alone rather than replaced with a guess.

---

## What each row gets, and why the test would fail if the behaviour regressed

| Row | Pinned by | Why it is a real pin |
|---|---|---|
| 7 | `SwitchTests::test_a_stream_switch_never_rewinds_the_chunk_index` | `buffer_index` is read **immediately after `change_stream` returns**, before any further read, and must not have gone backwards — that assertion is what pins the row. The *same open client connection* then reads PID `0x200` where it had been reading `0x100`, which is the "does not disturb connected clients" half. **Break-checked**: adding `self.index = 0` and a delete of the index key to `reset_buffer_position` fails it with `AssertionError: 0 not greater than or equal to 74`. Without the immediate read the same break **passes** — see Task 4 Step 3. |
| 8 | `PositioningTests::test_a_new_client_starts_behind_live` | A client that joined at the buffer head could only receive bytes as fast as the upstream produces them. This one drains 60 packets in less than half the wall clock live delivery would need. **Break-checked**: with `new_client_behind_seconds = 0` the assertion fails (`0.10996 not less than 0.02256`). |
| 9 | `PacketStreamTests::test_the_delivered_stream_is_whole_packets_in_unbroken_order` | 400 delivered packets are 188-byte aligned and their continuity counters advance by exactly 1 mod 16 with no break. A realignment that dropped or duplicated bytes at a chunk boundary breaks the counter chain. The stand-in copies in 8,192-byte reads (`harness/standin.py:45`), which is **not** a multiple of 188, so partial packets genuinely occur. |
| 10 | the two existing `shared-upstream.spec.ts` pins **plus** `ClientSetTests::test_the_client_set_from_three_sharing_clients_to_an_empty_channel` | `FakeUpstream.request_count` is 1 with three clients attached, and still 1 after the channel is stopped and every client's stream has ended. A second upstream connection would raise it. |
| 13 | `ClientSetTests::…` (registration) **and** `GhostClientTests::test_a_client_whose_last_active_goes_stale_is_removed` | Registration: a second tune carrying an already-registered `X-Relay-Client` is answered **503 `{"error": "Failed to register client"}`** and `client_count` stays 3. Ghost: with the heartbeat interval at 1 s and `GHOST_CLIENT_MULTIPLIER` at 0.1, a client whose upstream has gone silent is dropped in ≈ 0.65 s — far inside the 4 s budget the test asserts, and far outside the only other disconnect path (`stream_timeout + failover_grace_period` = 40 s, which the test asserts is larger). |

---

## Findings — produced by writing this plan, owned by nobody yet

Neither is fixed here: both are production changes, and 2a-3 adds tests.

**1. `CoreSettings.invalidate_group_cache` cannot clear the relay's own settings cache.** For `proxy_settings` it calls `BaseConfig.clear_proxy_settings_cache()` (`core/models.py:356-363`), but `get_proxy_settings` assigns `cls._proxy_settings_cache` on whichever class it was reached through, and every proxy read goes through `TSConfig` (`config_helper.py:5`, `:49-51`). `TSConfig` therefore holds its own attribute shadowing `BaseConfig`'s, and clearing the parent leaves it untouched. Verified in a shell against this tree:

```
TSConfig own dict has cache?   True
BaseConfig own dict has cache? True
after BaseConfig.clear -> TSConfig._proxy_settings_cache = {'marker': 'tsconfig-copy'}
after TSConfig.clear   -> TSConfig._proxy_settings_cache = None
```

`CLAUDE.md` § Known defects already says "saving clears the cache only in the worker that handled the write". This is narrower and worse: **it clears it in no worker that reads through `TSConfig`**, which is all of them on the proxy path. The 10-second TTL is what actually ends the staleness, so the observable effect matches the documented one and nobody has noticed. `ControlMixin.set_proxy_setting()` works around it by clearing `TSConfig` itself.

**2. A repeated `X-Relay-Client` is refused with 503, not attached.** `add_client` returns `False` for an id it has already registered (`client_manager.py:215-221`) and `stream_ts` turns that into `503 {"error": "Failed to register client"}` (`views.py:712-722`). Unreachable in production, because the authorize hop mints a fresh id per tune (`authorize.py:434`), which is why it is pinned as behaviour here rather than filed. **It becomes reachable the moment anything reuses a client id across a reconnect** — worth carrying into 2c's brief, since a Go relay's reconnect handling is exactly where that would happen.

---

## A materialised copy exists, and it predates this plan's fixes

The review pass wrote every code block in the **first** version of this plan out to a working tree and ran it. If `<scratchpad>/rev3/` still exists in your session it holds `repo/` (this plan's three files plus the five matrix row edits), `assemble.py` (per-task reassembly), `breaks.sh` / `breaks2.sh` with their logs, and `run1.log` — the DEBUG run behind Task 3 Step 3's expected log lines. **`breaks2.sh` carries the row 7 break**, so you can watch it go red and then green rather than trusting Step 4's description.

**Use it to transcribe, never to skip a step.** It is the pre-review state and carries the defects this plan now fixes — verified, not assumed: `test_relay_client_stream.py:126` has `DEAD_AIR_PACKETS = 200` and `:135` has `GHOST_MULTIPLIER = 0.1`; `harness/control.py:129-130` clears only `TSConfig`; and `test_relay_stream_switch.py` has no `right_after` read at all, so **row 7 is unpinned there**. Also missing, because both are prose-only steps: the README section (Task 2 Step 4) and the `CLAUDE.md` sentence (Task 3 Step 5). If the directory is gone, the plan's blocks are the source of truth — they are complete, and they are what was verified.

---

## Sequencing note for the orchestrator

This PR edits **row 10 at `docs/relay-parity-matrix.md:183`**, and **row 11 sits at `:184`**. The matrix's own comment records that git conflicts on edits one line apart and merges cleanly at two, so 2a-6's re-pin of row 11 — which its Notes invite — **must sequence after this PR merges**, or the two edits conflict. This PR's row 10 edit is spec-required (the `2a-3` row of § The seven PRs names row 10), so it is not the one to drop.

---

## Task 1: The first delivered-bytes test (matrix row 9)

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_relay_client_stream.py`
- Modify: `docs/relay-parity-matrix.md:167`

**Interfaces:**
- Consumes: `harness.relay.RelayHarnessTestCase` (`stand_in()`, `make_channel()`, `tune()`, `stop_channel()`), `harness.process.stand_in_stream_profile`, `harness.asset.{TS_PACKET_SIZE, assert_ts_aligned}` — all shipped by 2a-2.
- Produces: the module `apps/proxy/live_proxy/tests/test_relay_client_stream.py` and the module-level constant `SOURCE_PID = 0x100`, which Tasks 2 and 3 add classes to and reuse.

- [ ] **Step 1: Start your own test container**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3
DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a3 \
DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-2a3 \
.claude/hooks/start-test-container.sh
```

Expected: `==> ready`, preceded by `redis:    PONG` and `postgres: … accepting connections`.

Set `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-2a3` in your environment for the rest of the session so the `PostToolUse` edit hook uses your container and not the shared one.

- [ ] **Step 2: Write the test module**

Create `apps/proxy/live_proxy/tests/test_relay_client_stream.py`:

```python
"""What a client actually receives from the relay, and what the client set does.

Matrix rows 9, 10 and 13 (docs/relay-parity-matrix.md). Every assertion here is
about something a client or an admin can observe over HTTP -- delivered bytes,
a status field, a response status -- because that is what ports to a Go test
row-for-row (spec section "The subprocess harness", the composition rule).
"""

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase

# The PID synthetic_ts() writes by default (harness/asset.py:21).
SOURCE_PID = 0x100


def continuity_counters(data):
    """The 4-bit continuity counter of every 188-byte packet in `data`.

    Byte 3's low nibble, per the TS header synthetic_ts() builds
    (harness/asset.py:40: `0x10 | (i % 16)`).
    """
    return [data[offset + 3] & 0x0F for offset in range(0, len(data), TS_PACKET_SIZE)]


class PacketStreamTests(RelayHarnessTestCase):
    def test_the_delivered_stream_is_whole_packets_in_unbroken_order(self):
        """Matrix row 9: realignment to 188-byte boundaries, partials carried forward.

        The relay never sees the upstream's writes as packets. The stand-in
        copies its input in 8,192-byte reads (harness/standin.py:45) and 8,192
        is not a multiple of 188, so StreamBuffer.add_chunk is genuinely handed
        buffers that end mid-packet and genuinely has to carry the remainder
        (input/buffer.py:79-91). If it dropped or duplicated the remainder, the
        continuity-counter chain below would break at a chunk boundary -- which
        is exactly what a client's decoder would see.
        """
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            body = self.tune(channel, read_bytes=400 * TS_PACKET_SIZE)
            self.stop_channel(channel)

        assert_ts_aligned(body)
        counters = continuity_counters(body)
        breaks = [
            index
            for index in range(1, len(counters))
            if counters[index] != (counters[index - 1] + 1) % 16
        ]
        self.assertEqual(breaks, [], "continuity counters must advance by 1 mod 16")
```

Note on the payload: `FakeUpstream`'s default is `synthetic_ts(packets=512)` and 512 is a multiple of 16, so the counter chain is continuous **across** the payload's loop boundary too — packet 511 carries 15 and packet 0 carries 0. Nothing here depends on the client's start position, only on adjacent deltas.

- [ ] **Step 3: Run the package**

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests -v1 --durations 5
```

Expected: `Ran 180 tests`, `OK`. The new test appears in the durations list at roughly **0.7 s**.

(The `PostToolUse` hook runs the same package automatically on the Write; this command is here so you can re-run it and read `--durations`, which the hook does not pass.)

- [ ] **Step 4: Close matrix row 9**

In `docs/relay-parity-matrix.md`, on the single line beginning `| 9 | `, replace the Pin cell only. Change:

```
`owed: 2a-3`
```

to:

```
`apps/proxy/live_proxy/tests/test_relay_client_stream.py::PacketStreamTests::test_the_delivered_stream_is_whole_packets_in_unbroken_order`
```

Leave the `#`, `Behaviour`, `Source` and `Notes` cells byte-for-byte unchanged. Do not pad the cells. Do not let an editor reformat the table.

- [ ] **Step 6: Run the parity guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3/e2e
[ -d node_modules ] || npm ci
npx playwright test --project=guards parity-matrix
```

Expected: all guard tests pass, and the console line reads
`parity matrix: 28 rows — 6 pinned, 20 owed, 2 white-box-only.`
(Before this task it reads `5 pinned, 21 owed`.) The `guards` project needs no container.

- [ ] **Step 6: Commit**

Stage:

```bash
git add apps/proxy/live_proxy/tests/test_relay_client_stream.py docs/relay-parity-matrix.md
```

Then, in a **separate** Bash call, write the message to a file with the Write tool and commit it with `-F`. The `PreToolUse` gate runs before the command and blocks any single call that both stages and commits; it matches on command text, so a heredoc carrying those words trips it too. Message body:

```
test(phase2): the delivered TS stream is whole packets in unbroken order (row 9)

A tune reads 400 packets and asserts 188-byte alignment plus an unbroken
continuity-counter chain. The stand-in copies in 8,192-byte reads, which is
not a multiple of 188, so add_chunk really does carry partial packets across
chunk boundaries -- a drop or duplicate there breaks the chain.

Closes parity-matrix row 9.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Task 2: The control helpers and the client-set test (matrix rows 10 and 13's registration half)

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/control.py`
- Modify: `apps/proxy/live_proxy/tests/test_relay_client_stream.py` (add `ClientSetTests`)
- Modify: `apps/proxy/live_proxy/tests/harness/README.md`
- Modify: `docs/relay-parity-matrix.md:183` (row 10)

**Interfaces:**
- Consumes: Task 1's module and its `SOURCE_PID`; `harness.relay._TunedStream` and `harness.relay.wait_until`; `apps.proxy.internal_auth.{HEADER_AUTHORIZED, HEADER_RELAY_CHANNEL, HEADER_RELAY_CLIENT, relay_trust_token}`.
- Produces, for Tasks 3 and 4:
  - `harness.control.nginx_headers(channel, client_id) -> dict`
  - `harness.control.open_tune(case, channel, *, headers=None, timeout=20.0, expect_status=200) -> (requests.Response, _TunedStream)`
  - `harness.control.PROXY_SETTINGS_DEFAULTS: dict`
  - `harness.control.ControlMixin` with `admin_headers()`, `set_proxy_setting(**overrides)`, `status(channel) -> (int, dict)`, `change_stream(channel, url) -> Response`, `stop_channel_over_http(channel) -> Response`, `stop_client(channel, client_id) -> Response`

- [ ] **Step 1: Write the control helpers**

Create `apps/proxy/live_proxy/tests/harness/control.py`:

```python
"""Drive the relay's CONTROL surfaces over real HTTP, as a real principal.

2a-2's harness drives the stream surface. This drives the other four routes an
operator uses -- /proxy/ts/status/<uuid>, /change_stream/, /stop/, /stop_client/
-- plus the one thing a tune sometimes needs that `tuned()` deliberately does
not offer: a chosen client id, and a non-200 answer.

Everything here goes through production mechanisms, not test seams:

  * The admin principal is a real User row with an api_key, authenticated by
    apps/accounts/authentication.py's ApiKeyAuthentication through the
    X-API-Key header -- one of the two DEFAULT_AUTHENTICATION_CLASSES
    (dispatcharr/settings.py:321-324).

  * A chosen client id is supplied the way nginx supplies one:
    X-Dispatcharr-Authorized carrying HMAC(SECRET_KEY, "relay-trust") plus
    X-Relay-Channel and X-Relay-Client. resolve_authorization() trusts those
    headers only when the marker matches (apps/proxy/authorize_views.py:103-136),
    and stream_ts then uses `decision.client_id` rather than minting one
    (apps/proxy/live_proxy/views.py:194). This is nginx's own contract, so a
    test written against it ports to the Go relay unchanged.

  * proxy_settings is written as a CoreSettings row and the process-local cache
    is cleared, which is exactly what saving the setting in the UI does.

A NEW FILE ON PURPOSE. 2a-3, 2a-4, 2a-5 and 2a-6 develop in parallel against
this harness; adding a parameter to relay.py's tuned() would put four PRs on one
line. open_tune() below reaches _TunedStream directly instead -- same package,
no edit.
"""

import json
import uuid as uuid_module

import requests

from apps.proxy.internal_auth import (
    HEADER_AUTHORIZED,
    HEADER_RELAY_CHANNEL,
    HEADER_RELAY_CLIENT,
    relay_trust_token,
)

from .relay import _TunedStream

# BaseConfig.get_proxy_settings()'s own fallback dict (apps/proxy/config.py:52-59),
# repeated here so set_proxy_setting() writes a WHOLE group rather than a partial
# one: CoreSettings holds one row per settings group, so a partial write is a
# partial group, and the next reader silently falls back for everything missing.
PROXY_SETTINGS_DEFAULTS = {
    "buffering_timeout": 15,
    "buffering_speed": 1.0,
    "redis_chunk_ttl": 60,
    "channel_shutdown_delay": 0,
    "channel_init_grace_period": 60,
    "channel_client_wait_period": 5,
    "new_client_behind_seconds": 5,
}


def nginx_headers(channel, client_id):
    """The three headers nginx sets on a relay-bound location for this tune."""
    return {
        HEADER_AUTHORIZED: relay_trust_token(),
        HEADER_RELAY_CHANNEL: str(channel.uuid),
        HEADER_RELAY_CLIENT: client_id,
    }


def open_tune(case, channel, *, headers=None, timeout=20.0, expect_status=200):
    """GET /proxy/ts/stream/<uuid>, left open; return (response, reader).

    Like RelayHarnessTestCase.tuned() but not a context manager, because a test
    that wants several clients at once needs them all open simultaneously, and
    because a test may expect a non-200. The response is closed by addCleanup.

    NEVER read `response.text` on a 200: the body of a live stream does not end,
    and `timeout` is a socket timeout rather than a wall-clock one, so a status
    message built eagerly hangs forever (harness/relay.py:215-221).
    """
    response = requests.get(
        f"{case.live_server_url}/proxy/ts/stream/{channel.uuid}",
        stream=True,
        timeout=timeout,
        headers=headers,
    )
    case.addCleanup(response.close)
    case.assertEqual(response.status_code, expect_status)
    return response, _TunedStream(response, timeout=timeout)


class ControlMixin:
    """Mixed into a RelayHarnessTestCase that drives the admin control routes."""

    def admin_headers(self):
        """An admin principal, created on first use.

        Created lazily and per test: TransactionTestCase flushes every table
        between tests, so a class-level or setUpTestData user would not survive
        (harness/README.md, Two traps).
        """
        if not hasattr(self, "_admin_headers"):
            from apps.accounts.models import User

            key = uuid_module.uuid4().hex
            User.objects.create_user(
                username=f"harness-admin-{key[:8]}",
                password="unused-password",
                user_level=User.UserLevel.ADMIN,
                api_key=key,
            )
            self._admin_headers = {"X-API-Key": key}
        return self._admin_headers

    def set_proxy_setting(self, **overrides):
        """Write the proxy_settings group and invalidate BOTH of its caches.

        There are two, and clearing only the process-local one leaves the
        override in place for the rest of the test process. TransactionTestCase
        flushes with TRUNCATE, which fires no post_delete, so CoreSettings'
        Redis group cache (core/models.py:220-222, 300-second TTL) keeps
        serving the value after the row it came from is gone -- and the
        process-local copy is then refilled from the poisoned Redis entry.
        Measured: the DB row was empty and the next test class still read the
        override.

        Both are cleared explicitly, and the second call is NOT redundant.
        invalidate_group_cache deletes the Redis entry and bumps the version
        key so an in-flight fill cannot re-poison it, and it does try to clear
        the process-local copy -- but it calls
        `BaseConfig.clear_proxy_settings_cache()` (core/models.py:356-363),
        which cannot reach the relay's copy. `get_proxy_settings` assigns
        `cls._proxy_settings_cache` on whichever class it was called through,
        and every proxy read goes through `TSConfig` (config_helper.py:5), so
        `TSConfig` holds its own attribute shadowing `BaseConfig`'s. Verified
        in a shell: after `BaseConfig.clear_proxy_settings_cache()`,
        `TSConfig._proxy_settings_cache` still held its value; after
        `TSConfig.clear_proxy_settings_cache()` it was None. That is a
        production defect, not a test-only quirk -- see the plan's Findings --
        and until it is fixed a test must clear the subclass itself.
        """
        from apps.proxy.config import TSConfig
        from core.models import PROXY_SETTINGS_KEY, CoreSettings

        def _invalidate():
            CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)
            TSConfig.clear_proxy_settings_cache()

        CoreSettings.objects.update_or_create(
            key=PROXY_SETTINGS_KEY,
            defaults={"value": {**PROXY_SETTINGS_DEFAULTS, **overrides}},
        )
        _invalidate()
        self.addCleanup(_invalidate)

    def status(self, channel):
        """GET /proxy/ts/status/<uuid> as an admin; return (status_code, body)."""
        response = requests.get(
            f"{self.live_server_url}/proxy/ts/status/{channel.uuid}",
            headers=self.admin_headers(),
            timeout=10,
        )
        return response.status_code, response.json()

    def change_stream(self, channel, url):
        """POST /proxy/ts/change_stream/<uuid> with an explicit url."""
        return requests.post(
            f"{self.live_server_url}/proxy/ts/change_stream/{channel.uuid}",
            headers={**self.admin_headers(), "Content-Type": "application/json"},
            data=json.dumps({"url": url}),
            timeout=30,
        )

    def stop_channel_over_http(self, channel):
        """POST /proxy/ts/stop/<uuid>.

        Named for the surface, not the action, because RelayHarnessTestCase
        already has stop_channel() -- the in-process teardown its cleanup uses.
        """
        return requests.post(
            f"{self.live_server_url}/proxy/ts/stop/{channel.uuid}",
            headers=self.admin_headers(),
            timeout=30,
        )

    def stop_client(self, channel, client_id):
        """POST /proxy/ts/stop_client/<uuid>."""
        return requests.post(
            f"{self.live_server_url}/proxy/ts/stop_client/{channel.uuid}",
            headers={**self.admin_headers(), "Content-Type": "application/json"},
            data=json.dumps({"client_id": client_id}),
            timeout=30,
        )
```

- [ ] **Step 2: Add the client-set test**

Extend the imports at the top of `apps/proxy/live_proxy/tests/test_relay_client_stream.py` so they read:

```python
from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.control import ControlMixin, nginx_headers, open_tune
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
```

Then append this class to the same module:

```python
class ClientSetTests(ControlMixin, RelayHarnessTestCase):
    def test_the_client_set_from_three_sharing_clients_to_an_empty_channel(self):
        """Matrix row 10, and row 13's registration half.

        One narrative because it is one channel's client set, and because each
        step needs the previous one's state: three clients on one upstream, a
        fourth request reusing a registered client id, one client stopped by the
        operator, then the whole channel stopped. The upstream's request_count
        is the load-bearing observation -- it is 1 at the start and still 1 at
        the end, so nothing along the way opened a second provider connection.
        """
        client_id = "harness-doomed-client"
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

            # The first client takes a chosen id (so the operator can name it
            # below); the other two get relay-minted ones.
            readers = []
            for headers in (nginx_headers(channel, client_id), None, None):
                _, reader = open_tune(self, channel, headers=headers)
                reader.read(4 * TS_PACKET_SIZE)
                readers.append(reader)

            _, info = self.status(channel)
            self.assertEqual(self.upstream.request_count, 1)
            self.assertEqual(info["client_count"], 3)

            # Row 13, registration: add_client() refuses a client id it has
            # already seen (client_manager.py:215-221) and stream_ts turns that
            # into a 503 rather than a second registration (views.py:712-722).
            duplicate, _ = open_tune(
                self, channel, headers=nginx_headers(channel, client_id), expect_status=503
            )
            self.assertEqual(duplicate.json(), {"error": "Failed to register client"})
            self.assertEqual(self.status(channel)[1]["client_count"], 3)

            # ChannelService.stop_client: the named client's stream ends, the
            # other two keep receiving.
            response = self.stop_client(channel, client_id)
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.json()["locally_processed"], True)
            with self.assertRaises(AssertionError):
                readers[0].read(4000 * TS_PACKET_SIZE)
            readers[1].read(4 * TS_PACKET_SIZE)
            readers[2].read(4 * TS_PACKET_SIZE)
            wait_until(
                lambda: self.status(channel)[1]["client_count"] == 2,
                timeout=10,
                what="the stopped client to leave the channel's client list",
            )

            # ChannelService.stop_channel: every remaining stream ends, and the
            # upstream was never reconnected.
            response = self.stop_channel_over_http(channel)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["previous_state"], {"state": "active"})
            for reader in readers[1:]:
                with self.assertRaises(AssertionError):
                    reader.read(4000 * TS_PACKET_SIZE)
            self.assertEqual(self.upstream.request_count, 1)
```

A note on the `assertRaises(AssertionError)` blocks, because an earlier draft got the arithmetic backwards and undersold them. `_TunedStream.read` raises `AssertionError` two ways (`harness/relay.py:60-74`): the response ended, or the deadline passed. The request is `4000 * TS_PACKET_SIZE` = 752,000 bytes, and at the paced upstream's 250 KB/s that is **3.0 seconds** — comfortably inside `_TunedStream`'s 20-second deadline. So on a stream that is still being served the read *succeeds*, and the raise means the stream ended. **The assertion is a direct proof, not a weak one.** The assertions that follow — `readers[1]`/`readers[2]` still getting bytes, `client_count` dropping to exactly 2 — are corroboration that the stop was targeted rather than general, not the load-bearing part.

- [ ] **Step 3: Run the package**

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests -v1 --durations 5
```

Expected: `Ran 181 tests`, `OK`. The new test costs roughly **0.9 s**. Two lines appear on stderr at ERROR level and are expected, not a failure — they are the 503 the test asserts:

```
ERROR live_proxy.views [harness-doomed-client] Failed to register client with channel <uuid>
ERROR django.request Service Unavailable: /proxy/ts/stream/<uuid>
```

- [ ] **Step 4: Document `control.py` in the harness README**

In `apps/proxy/live_proxy/tests/harness/README.md`, insert a new section immediately after the fenced example that ends § Writing a test, and before `## The fault vocabulary`. Title it `## Driving the control surfaces`, and give it:

- a short fenced Python example showing a class declared as `class MyTests(ControlMixin, RelayHarnessTestCase)` and calling `self.status(channel)`, `self.change_stream(channel, other.url)`, `self.stop_client(channel, client_id)`, `self.stop_channel_over_http(channel)`, `self.set_proxy_setting(new_client_behind_seconds=0.5)` and `open_tune(self, channel, headers=nginx_headers(channel, "my-client"))`;
- four bullets, each one sentence plus its reason:
  - the admin principal is a real `User` row with an `api_key`, sent as `X-API-Key`, created on first use and gone with the test's flush;
  - `nginx_headers()` is nginx's own contract, not a test seam — `X-Dispatcharr-Authorized` carries `HMAC(SECRET_KEY, "relay-trust")` and `resolve_authorization()` trusts `X-Relay-Client` only when it matches, which is the only way to choose a client id because `stream_ts` otherwise mints one;
  - `set_proxy_setting()` writes the whole group, clears `TSConfig._proxy_settings_cache` and registers the cleanup that clears it again, because that cache is a class attribute with a 10-second TTL and an override left behind leaks into unrelated tests;
  - `open_tune()` is not a context manager, because a test with several simultaneous clients needs them all open at once; the responses are closed by `addCleanup`.

Prose only — no guard parses this file, so match the surrounding style rather than a template.

- [ ] **Step 5: Re-pin matrix row 10**

Row 10 is **already pinned** — it carries two `shared-upstream.spec.ts` references and is *not* `owed: 2a-3`. Its Notes invite a harness re-pin ("2a-3 may re-pin this to a harness test; the existing e2e specs stand until it does"). Add the harness test as a **third** reference and keep both e2e ones: the e2e specs prove the behaviour through nginx and a real container, the harness test proves it in-process where a Go port can copy it.

On the single line beginning `| 10 | `, change the Pin cell from:

```
`e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection`, `e2e/tests/streaming/shared-upstream.spec.ts::closing every client releases the upstream`
```

to:

```
`e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection`, `e2e/tests/streaming/shared-upstream.spec.ts::closing every client releases the upstream`, `apps/proxy/live_proxy/tests/test_relay_client_stream.py::ClientSetTests::test_the_client_set_from_three_sharing_clients_to_an_empty_channel`
```

and, on the same line, change the final sentence of the Notes cell from:

```
2a-3 may re-pin this to a harness test; the existing e2e specs stand until it does
```

to:

```
2a-3 added the third pin, a harness test that asserts the same two things in-process: the upstream's request count is 1 with three clients attached and still 1 once the channel has been stopped and every stream has ended. All three stand
```

This is one line's Pin and Notes cells; the `#`, `Behaviour` and `Source` cells are untouched. Fixing the stale sentence is part of the edit, not optional — a Notes clause that still says the row is unpinned by a harness test is exactly the kind of sentence this programme keeps finding left behind.

- [ ] **Step 6: Run the parity guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3/e2e
npx playwright test --project=guards parity-matrix
```

Expected: pass, with `parity matrix: 28 rows — 6 pinned, 20 owed, 2 white-box-only.` The **pinned count does not change in this task** — row 10 was already pinned; only its reference list grew.

- [ ] **Step 7: Commit**

Stage:

```bash
git add apps/proxy/live_proxy/tests/harness/control.py apps/proxy/live_proxy/tests/harness/README.md apps/proxy/live_proxy/tests/test_relay_client_stream.py docs/relay-parity-matrix.md
```

Then commit in a separate call with `-F` and this message:

```
test(phase2): the control helpers, and one channel from three clients to none (row 10)

harness/control.py drives the four admin routes over real HTTP as a real
api-key admin, writes proxy_settings through the production lever, and opens
a tune carrying the headers nginx would have set -- which is the only way to
choose a client id, since stream_ts otherwise mints one.

A new file rather than a parameter on relay.py's tuned(): four coverage PRs
develop against this harness in parallel.

Re-pins parity-matrix row 10 with a third reference alongside the two e2e
specs, which stand.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Task 3: The ghost-client test (closes matrix row 13)

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_relay_client_stream.py` (add `GhostClientTests`)
- Modify: `docs/relay-parity-matrix.md:168` (row 13)
- Modify: `CLAUDE.md` (§ Testing, line 138)

**Interfaces:**
- Consumes: Task 1's `SOURCE_PID` and `assert_ts_aligned`; Task 2's `ControlMixin` and `open_tune`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the test**

Add `import time` and `from unittest.mock import patch` to the top of `apps/proxy/live_proxy/tests/test_relay_client_stream.py` (stdlib first, then the `unittest.mock` import, then the existing `from .harness…` block), then append:

```python
# How much the stand-in produces before going silent is DERIVED, not measured:
# the channel has to hold at least `initial_behind_chunks()` chunks before a
# client can be positioned in it, so anything less aborts in initialization
# instead of reaching the ghost sweep -- which is a green test pinning the
# wrong thing. Doubled for margin. See _dead_air_bytes() below, which reads
# BUFFER_CHUNK_SIZE at call time because RelayHarnessTestCase patches it.
DEAD_AIR_CHUNK_MARGIN = 2
# Must be an int >= 1: the heartbeat loop sleeps `for _ in range(int(interval))`
# in one-second steps (client_manager.py:82-85), so 1 is the shortest cycle
# that exists and 0 would busy-loop.
HEARTBEAT_SECONDS = 1
# ghost_timeout = heartbeat_interval * this (client_manager.py:116), read fresh
# on every heartbeat pass, so unlike the interval it is not snapshotted in
# ClientManager.__init__ and can be pushed well below the generator's own
# 1-second stats-write throttle.
GHOST_MULTIPLIER = 2.0


class GhostClientTests(ControlMixin, RelayHarnessTestCase):
    @staticmethod
    def _dead_air_bytes():
        """Enough bytes to fill the buffer a client needs before it can attach."""
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        return (
            DEAD_AIR_CHUNK_MARGIN
            * ConfigHelper.initial_behind_chunks()
            * TSConfig.BUFFER_CHUNK_SIZE
        )

    def test_a_client_whose_last_active_goes_stale_is_removed(self):
        """Matrix row 13's ghost half.

        The client stays connected and asks for more bytes throughout. What
        ends its stream is the heartbeat thread noticing that its `last_active`
        is older than GHOST_CLIENT_MULTIPLIER x the heartbeat interval
        (client_manager.py:112-120), removing it, and the generator's next
        resource check finding it gone (output/ts/generator.py:421-423).
        """
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        # Four heartbeat cycles. The assertion below is only meaningful if
        # nothing ELSE could have ended the stream inside that window, and the
        # only other thing that ends an idle client is the generator's own
        # inactivity timeout -- so assert that it is far larger, rather than
        # asserting a number somebody measured once.
        # The ghost timeout is GHOST_MULTIPLIER x the interval; allow two more
        # heartbeat cycles for the check that follows it to land. Derived, so
        # changing the multiplier cannot leave the budget behind.
        budget = (GHOST_MULTIPLIER + 2) * HEARTBEAT_SECONDS
        self.assertGreater(
            ConfigHelper.stream_timeout() + ConfigHelper.failover_grace_period(), budget
        )

        with patch.object(TSConfig, "CLIENT_HEARTBEAT_INTERVAL", HEARTBEAT_SECONDS), patch.object(
            TSConfig, "GHOST_CLIENT_MULTIPLIER", GHOST_MULTIPLIER
        ):
            with self.stand_in(dead_air_after_bytes=self._dead_air_bytes()):
                profile = stand_in_stream_profile()
                channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
                _, reader = open_tune(self, channel, timeout=budget)

                # Bounded by wall clock, not only by the read failing: on a
                # stream that never ends this loop never ends either, and a
                # hung test is a worse failure than a red one. `ended` records
                # whether the stream actually stopped, which is the thing
                # under test -- the deadline is only the escape hatch.
                received, started, ended = b"", time.monotonic(), False
                while time.monotonic() - started < budget:
                    try:
                        received += reader.read(TS_PACKET_SIZE)
                    except AssertionError:
                        ended = True
                        break
                ended_after = time.monotonic() - started
                self.assertTrue(
                    ended,
                    f"the client was still being served {ended_after:.2f}s after "
                    f"its last_active stopped advancing; the ghost sweep never "
                    f"removed it",
                )

                self.assertLess(ended_after, budget)
                # The client received a real stream before it was dropped, not
                # a single relay-minted error packet -- which is what an
                # initialization abort looks like, and is how this test would
                # otherwise pass for the wrong reason.
                assert_ts_aligned(received)
                self.assertGreaterEqual(len(received), TSConfig.BUFFER_CHUNK_SIZE)
                self.assertEqual(((received[1] & 0x1F) << 8) | received[2], SOURCE_PID)

                self.stop_channel(channel)
```

**The dead air is load-bearing, and an earlier draft's was not.** That draft used `GHOST_MULTIPLIER = 0.1`, which puts the ghost timeout at 0.1 s — *shorter than the generator's own 1-second stats-write throttle* (`output/ts/generator.py:78`, `:499`), the only thing that advances `last_active` for a streaming client. Every client is therefore stale at every heartbeat check, and the test passed with a perfectly healthy stand-in: verified, `Ran 1 test in 1.625s OK`. It was pinning "the heartbeat thread removes clients", not "a client whose `last_active` stops advancing is removed". At `GHOST_MULTIPLIER = 2.0` the timeout is 2 s, comfortably above the throttle, and the same test **fails** against a healthy stand-in with *"the client was still being served 4.02s after its last_active stopped advancing"*. That is the difference between a premise and a decoration, and it costs about 2.2 s.

Three things this test deliberately does **not** do, each learned by measuring:

- **It does not loop unbounded.** `while True: received += reader.read(...)` ends only when a read fails, and on a healthy stream it never does — the test hangs rather than failing, which is strictly worse. The loop is bounded by `budget` and `ended` records whether the stream actually stopped, so the healthy case fails with a sentence instead of hanging.
- **It does not assert an exact byte count.** How much the client drains before the sweep removes it varies with process warmth; observed 15,040 / 31,960 / 37,600 bytes in the full package. (An earlier draft blamed this on the generator's positioning fallbacks — **wrong**: `INFO` logs show `Time-based positioning: 5s behind -> index 0` on every run, so the client always starts at the oldest chunk and the fallbacks are never reached.)
- **It does not assert the channel's state or client count afterwards.** This client is the channel's only one, so with `channel_shutdown_delay` at 0 the channel may start tearing down the moment it goes, and `GET /proxy/ts/status/<uuid>` then answers **404** rather than a payload with `client_count: 0`. An earlier draft asserted `client_count == 0` and failed intermittently with `KeyError: 'client_count'`.

- [ ] **Step 2: Run the package, twice**

```bash
for i in 1 2; do
  docker exec dispatcharr-testrunner-2a3 redis-cli flushall
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
    -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
    -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
    -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
    dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
    manage.py test --keepdb apps.proxy.live_proxy.tests -v1 --durations 5
done
```

Expected: `Ran 182 tests`, `OK`, **both times**. The new test costs roughly **1.3 s**. Run it twice deliberately: this is the one test in the PR whose subject is a background thread's timing, and a single green run says less here than elsewhere.

- [ ] **Step 3: Prove the mechanism is the one the row names**

Re-run just this module with debug logging and confirm the three lines that show the ghost path, in order:

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=DEBUG \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests.test_relay_client_stream 2>&1 \
  | grep -E "removing as ghost|Identified .* ghost clients|no longer in client manager"
```

Expected — three lines, in this order (uuids and client ids will differ):

```
DEBUG live_proxy.client_manager Client client_… inactive for 0.4s, removing as ghost
INFO live_proxy.client_manager Identified 1 ghost clients for channel …
INFO live_proxy.generator [client_…] Client no longer in client manager, terminating stream
```

That is `client_manager.py:118-120` (the heartbeat-multiplier staleness check row 13 cites at `:100-126`), then `:122-126`, then `output/ts/generator.py:421-423`. If the first line is missing, whatever ended the stream was not the ghost mechanism and the test does not pin the row — stop and diagnose before continuing. The "inactive for" figure is a measurement and will vary; do not assert on it.

- [ ] **Step 4: Close matrix row 13**

On the single line beginning `| 13 | `, replace the Pin cell:

```
`owed: 2a-3`
```

becomes:

```
`apps/proxy/live_proxy/tests/test_relay_client_stream.py::ClientSetTests::test_the_client_set_from_three_sharing_clients_to_an_empty_channel`, `apps/proxy/live_proxy/tests/test_relay_client_stream.py::GhostClientTests::test_a_client_whose_last_active_goes_stale_is_removed`
```

Two references because the row states two behaviours: the first test pins the idempotent registration, the second the ghost removal.

The Notes cell's first sentence currently reads "Extends the existing `apps/channels/tests/test_ts_proxy_ghost_clients.py`, which is the partial cover the spec records." Leave it — it is still true, and the second half of the Notes (the two distinct ghost mechanisms) is what the reviewer needs.

- [ ] **Step 5: Correct `CLAUDE.md`**

In § Testing (line 138), the sentence

```
Exactly one test file talks to a real Redis; the lease and ring buffer never meet real Redis semantics — the fakes reimplement the Lua in Python, proving the reimplementation correct while saying nothing about atomicity.
```

is now wrong in both halves: the 2a-2 harness runs against real Redis, and from this PR the ring buffer's realignment, its monotonic chunk index and its timestamp-based client positioning are all asserted against it. Replace with:

```
The harness tests run against a real Redis and the real ring buffer — since Phase 2 PR 2a-3, its 188-byte realignment, its monotonic chunk index across a stream switch and its `chunk_timestamps` client positioning are all asserted there — but the **ownership lease** still never meets real Redis semantics: outside the harness the fakes reimplement the Lua in Python, proving the reimplementation correct while saying nothing about atomicity.
```

The lease clause survives on purpose: it is the defect § Known defects records, no harness test touches it, and deleting the sentence wholesale would delete a true warning along with a false one.

- [ ] **Step 6: Run the parity guard and the credential guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3/e2e
npx playwright test --project=guards parity-matrix
```

Expected: pass, `parity matrix: 28 rows — 7 pinned, 19 owed, 2 white-box-only.`

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3
python3 scripts/check_credential_logging.py apps/proxy/live_proxy/tests/test_relay_client_stream.py apps/proxy/live_proxy/tests/harness/control.py
```

Expected: no output, exit 0. (The `PostToolUse` hook runs this on every `.py` write; the explicit run is for your own confidence before the commit gate.)

- [ ] **Step 7: Commit**

Stage:

```bash
git add apps/proxy/live_proxy/tests/test_relay_client_stream.py docs/relay-parity-matrix.md CLAUDE.md
```

Then commit in a separate call with `-F` and this message:

```
test(phase2): a client whose last_active goes stale is dropped (closes row 13)

The client stays connected and keeps asking for bytes; what ends its stream
is the heartbeat thread finding last_active older than GHOST_CLIENT_MULTIPLIER
x the interval, and the generator noticing it is gone. The window asserted is
four heartbeat cycles, and the test first asserts that the only other thing
that could end an idle client needs forty seconds.

CLAUDE.md section Testing no longer claims the ring buffer never meets real
Redis semantics -- the harness tests assert exactly that. The ownership lease
clause stands: nothing here touches it.

Closes parity-matrix row 13.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Task 4: The switch and late-join tests (closes matrix rows 7 and 8)

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_relay_stream_switch.py`
- Modify: `docs/relay-parity-matrix.md:165` (row 7), `:166` (row 8)

**Interfaces:**
- Consumes: Task 2's `ControlMixin`, `open_tune`; `harness.upstream.{FakeUpstream, NOMINAL_BYTE_RATE}`; `harness.asset.synthetic_ts`; `harness.relay.wait_until`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the module**

Create `apps/proxy/live_proxy/tests/test_relay_stream_switch.py`:

```python
"""A running channel switched to another source, and a client that joins late.

Matrix rows 7 and 8. Both drive ChannelService's switch path and the TS
generator's client-positioning path through the admin HTTP surface -- which is
what makes them portable: the Go relay serves the same two routes.
"""

import time

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, synthetic_ts
from .harness.control import ControlMixin, open_tune
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .harness.upstream import NOMINAL_BYTE_RATE, FakeUpstream

# synthetic_ts()'s default PID, and a second one so a client can tell which
# source a packet came from without decoding anything.
FIRST_PID = 0x100
SECOND_PID = 0x200
# Short enough that a test does not have to buffer five real seconds. The
# DEFAULT is asserted separately below -- this is the compressed value.
BEHIND_SECONDS = 0.5


def pids(data):
    """Every distinct PID in `data`, read from the 13 bits after the sync byte."""
    return {
        ((data[offset + 1] & 0x1F) << 8) | data[offset + 2]
        for offset in range(0, len(data) - TS_PACKET_SIZE + 1, TS_PACKET_SIZE)
    }


class SwitchTests(ControlMixin, RelayHarnessTestCase):
    def test_a_stream_switch_never_rewinds_the_chunk_index(self):
        """Matrix row 7.

        One client stays connected across the switch and reads both sources'
        packets out of the same ring buffer, while buffer_index only ever goes
        up. That is the whole claim: reset_buffer_position() clears
        _write_buffer and _partial_packet and never touches self.index
        (input/buffer.py:136-168), which is why a switch does not disturb a
        connected client.
        """
        second = FakeUpstream(payload=synthetic_ts(packets=512, pid=SECOND_PID)).start()
        self.addCleanup(second.stop)

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel) as stream:
                self.assertEqual(pids(stream.read(20 * TS_PACKET_SIZE)), {FIRST_PID})
                _, before = self.status(channel)

                response = self.change_stream(channel, second.url)
                self.assertEqual(response.status_code, 200)
                # The relay applied the switch itself rather than publishing it
                # for another worker: change_stream_url's owner branch, which
                # is where update_url() and reset_buffer_position() are called.
                self.assertIs(response.json()["owner"], True)

                # Read the index NOW, before any further read can absorb the
                # gap -- this assertion is the whole row and it has to happen
                # here. A rewind restarts the new source's INCR at 1 while the
                # client sits far above it, so the client simply receives
                # nothing until the new numbering overtakes the old: about half
                # a second at this pacing, which the 1500-packet read below
                # swallows whole, after which the index has climbed past its
                # old value again. Asserted at this point the rewind is a 0
                # against an 80; asserted after the read it is invisible.
                # Measured: with `self.index = 0` and a delete of the index key
                # added to reset_buffer_position, the version of this test
                # WITHOUT these three lines still passed.
                _, right_after = self.status(channel)
                self.assertGreaterEqual(
                    right_after["buffer_index"], before["buffer_index"]
                )

                # The metadata write lands before the reconnect does, so
                # waiting on the status url would wait for the wrong thing.
                # Wait for the new upstream to actually be connected.
                wait_until(
                    lambda: second.request_count >= 1,
                    timeout=10,
                    what="the relay to connect to the new upstream",
                )
                after_switch = stream.read(1500 * TS_PACKET_SIZE)
                _, after = self.status(channel)

            assert_ts_aligned(after_switch)
            self.assertIn(SECOND_PID, pids(after_switch))
            self.assertGreater(after["buffer_index"], before["buffer_index"])
            self.assertEqual(after["url"], second.url)
            self.stop_channel(channel)


class PositioningTests(ControlMixin, RelayHarnessTestCase):
    def test_a_new_client_starts_behind_live(self):
        """Matrix row 8.

        A client positioned at the buffer head can only receive bytes as fast
        as the upstream produces them. A client positioned `behind_seconds`
        back has a backlog sitting in Redis and drains it at loopback speed.
        The threshold is derived from the upstream's own pacing, never from a
        measurement: `live_would_take` is what the same bytes would have cost
        at the wire rate, and the test asserts the drain beat half of it.
        """
        from apps.proxy.config import TSConfig
        from apps.proxy.live_proxy.config_helper import ConfigHelper

        # The row says "roughly 5 seconds behind live", so pin the default
        # before compressing it -- otherwise nothing in this suite asserts the 5.
        TSConfig.clear_proxy_settings_cache()
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), 5)
        self.set_proxy_setting(new_client_behind_seconds=BEHIND_SECONDS)
        self.assertEqual(ConfigHelper.new_client_behind_seconds(), BEHIND_SECONDS)

        bytes_per_second = self.upstream.rate * NOMINAL_BYTE_RATE
        chunks_for_the_window = int(
            BEHIND_SECONDS * bytes_per_second // TSConfig.BUFFER_CHUNK_SIZE
        )

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel) as first:
                first.read(4 * TS_PACKET_SIZE)
                # Twice the window, so find_chunk_index_by_time() has a chunk
                # old enough to answer with and does not fall through to its
                # oldest-available branch -- a different behaviour.
                wait_until(
                    lambda: self.status(channel)[1].get("buffer_index", 0)
                    >= 2 * chunks_for_the_window,
                    timeout=10,
                    what="twice the behind-live window to accumulate in the ring buffer",
                )

                _, joiner = open_tune(self, channel)
                started = time.monotonic()
                backlog = joiner.read(60 * TS_PACKET_SIZE)
                drained_in = time.monotonic() - started

            live_would_take = len(backlog) / bytes_per_second
            self.assertLess(drained_in, live_would_take / 2)
            self.stop_channel(channel)
```

- [ ] **Step 2: Run the package**

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests -v1 --durations 6
```

Expected: `Ran 184 tests`, `OK`. `test_a_stream_switch_never_rewinds_the_chunk_index` costs roughly **1.8 s** (about 1 s of it is the relay's own reconnect after `update_url`, which is not something a test can compress); `test_a_new_client_starts_behind_live` roughly **1.3 s**.

- [ ] **Step 3: Break-check the positioning test**

This is the test most at risk of passing for a reason other than the one it names, so prove it fails when the behaviour is absent. Temporarily change the module constant to `BEHIND_SECONDS = 0` and run just this module:

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests.test_relay_stream_switch -v1
```

Expected: `FAILED (failures=1)` with

```
FAIL: test_a_new_client_starts_behind_live …
AssertionError: 0.109… not less than 0.0225…
```

— the joining client took roughly five times longer than the half-of-live threshold, because at `behind_seconds = 0` it started at the buffer head and had to wait for the upstream. **Restore `BEHIND_SECONDS = 0.5` and re-run Step 2 before continuing.** The exact digits in the failure will differ; what matters is that the drain assertion is the one that fires.

- [ ] **Step 4: Break-check the switch test — this one caught a real defect in an earlier draft**

Row 7's whole claim is that a switch does not rewind the index, so break exactly that. In `apps/proxy/live_proxy/input/buffer.py`, inside `reset_buffer_position`'s `with self.lock:` block, add two lines above `old_write_size = len(self._write_buffer)`:

```python
                if self.redis_client:
                    self.redis_client.delete(self.buffer_index_key)
                self.index = 0
```

Run just the switch class:

```bash
docker exec dispatcharr-testrunner-2a3 redis-cli flushall
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
  manage.py test --keepdb apps.proxy.live_proxy.tests.test_relay_stream_switch.SwitchTests -v1
```

Expected: `FAILED (failures=1)` with

```
AssertionError: 0 not greater than or equal to 74
```

The `0` is the deleted index key, which `channel_status.py:37-46` reports as `0` rather than omitting; the second number is whatever the index had reached. **Restore `buffer.py` and re-run Step 2 before continuing.**

**Do not skip this step, and do not move the assertion.** An earlier draft of this plan asserted the index only *after* the 1500-packet read, and under the same break that version **passed** (`Ran 1 test in 2.976s OK`) while this one fails. The row would have shipped pinned to a test that could not observe the thing it names. That is the failure this stage exists to catch, and it was caught by review rather than by writing — which is the argument for running the break rather than reasoning about it.

- [ ] **Step 5: Close matrix rows 7 and 8**

On the line beginning `| 7 | `, replace `` `owed: 2a-3` `` with:

```
`apps/proxy/live_proxy/tests/test_relay_stream_switch.py::SwitchTests::test_a_stream_switch_never_rewinds_the_chunk_index`
```

On the line beginning `| 8 | `, replace `` `owed: 2a-3` `` with:

```
`apps/proxy/live_proxy/tests/test_relay_stream_switch.py::PositioningTests::test_a_new_client_starts_behind_live`
```

Both rows' `Source` and `Notes` cells are unchanged. Row 8's Notes already say `new_client_behind_seconds` defaults to 5 and that a separate expired-chunk recovery mechanism is *not* part of this behaviour — both still true: the test asserts the default is 5 before compressing it, and it waits for twice the window precisely so the expired-chunk branch is not the one exercised.

- [ ] **Step 6: Run the parity guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2a3/e2e
npx playwright test --project=guards parity-matrix
```

Expected: pass, `parity matrix: 28 rows — 9 pinned, 17 owed, 2 white-box-only.`

Nine pinned = the five that were pinned before this PR (10, 11, 21, 22, 24) plus 7, 8, 9, 13. Seventeen owed = twenty-one minus those four. `GATE_1_CLOSED` stays `false` and the guard's "the matrix is fully pinned when the flag says so" test takes its else branch, as it has since 2a-1.

- [ ] **Step 7: Commit**

Stage:

```bash
git add apps/proxy/live_proxy/tests/test_relay_stream_switch.py docs/relay-parity-matrix.md
```

Then commit in a separate call with `-F` and this message:

```
test(phase2): a switch keeps the chunk index and the client (closes rows 7, 8)

One client reads both sources out of the same ring buffer across a
change_stream, and buffer_index only goes up -- reset_buffer_position clears
the write buffer and the partial packet and never the index.

A late joiner drains a backlog faster than the upstream could have produced
it, which a client positioned at the buffer head cannot do. The threshold is
derived from the fake upstream's pacing; the default of five seconds is
asserted before being compressed to half a second.

Closes parity-matrix rows 7 and 8.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Task 5: The gate

**Files:** none changed. This task measures and reports.

- [ ] **Step 1: Decide whether to re-measure the branch point**

**Take your own baseline. Do not reuse the illustrative one in § Global Constraints** — it was measured on a different day under a named core, and the gate is relative, not absolute.

Check `27c9e79c` out into a scratch worktree, or move your own test files aside, and run the gate there first. Use a **different** `COVERAGE_LIVE_PATH_DATA_DIR` for each of the two measurements — `coverage combine` consumes its input files, so a second `--report` over the same directory finds nothing and says so. Take **three runs of each side**: `missing` is a sample from a band, and one run of each cannot tell a real change from the band's width.

Both measurements must come from the **same session, the same container and the same script**, so they carry the same tracer core. The script stamps the core into its shape id (`per-label/v2-${COVERAGE_CORE}`) and refuses to report over data written under another one — but that guard only sees data files, not two numbers you wrote into a PR description, so the discipline is yours to keep.

- [ ] **Step 2: Run the gate on your branch**

```bash
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
  -e COVERAGE_LIVE_PATH_DATA_DIR=/tmp/cov-2a3 \
  dispatcharr-testrunner-2a3 bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH; cd /repo; scripts/coverage_live_path.sh'
```

The last line reports the whole denominator:

```
coverage_live_path: statements 7978  missing <N>  coverage <P>%
```

**The denominator, 7,978, is the check.** It is a property of the rcfile and moves only if the module list does; if it differs, that is a finding, and it invalidates the comparison rather than merely changing it. **`<N>` is not a check** — it is a sample from a band, and no figure for it is written here on purpose.

**The gate, stated relatively:**

> On both `apps/proxy/live_proxy/output/ts/generator.py` and `apps/proxy/live_proxy/services/channel_service.py`, the branch shows **strictly fewer missed statements** than the same-session baseline, in **every** paired run.

Requiring it of every pair rather than of the means is what makes three runs worth taking: these two files were measured with a **zero-wide** spread across three runs on each side, so a pair that fails is a real change, not the band. Record all six figures and **name the tracer core** in the PR description.

- [ ] **Step 3: Measure the test-time cost**

```bash
for i in 1 2 3; do
  docker exec dispatcharr-testrunner-2a3 redis-cli flushall
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
    -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
    -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
    -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
    dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
    manage.py test --keepdb apps.proxy.live_proxy.tests -v1 2>&1 | grep -E '^Ran |^OK$'
done
```

Expected: `Ran 184 tests in 17.1–17.9s`, `OK`, three times. The branch point runs 179 tests in 6.0–6.6 s, so the added cost is **≈ 10.9 s**. Record the three figures in the PR description; do not round them into a claim that the stage budget is met.

- [ ] **Step 4: Run the two neighbouring labels**

The path aliases route `apps/proxy/live_proxy/` edits to `apps.proxy.live_proxy.tests` **and** `apps.channels.tests`, and the gate runs `apps.proxy.tests` too. All three ran green under Step 2; run the other two on their own so a failure would be attributable:

```bash
for L in apps.proxy.tests apps.channels.tests; do
  docker exec dispatcharr-testrunner-2a3 redis-cli flushall
  docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
    -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
    -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
    -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=ERROR \
    dispatcharr-testrunner-2a3 /dispatcharrpy/bin/python \
    manage.py test --keepdb "$L" -v1 2>&1 | grep -E '^Ran |^OK$|^FAILED'
done
```

Expected: `Ran 278 tests … OK` and `Ran 441 tests … OK`.

- [ ] **Step 5: Tear down your container**

```bash
docker rm -f dispatcharr-testrunner-2a3
docker volume rm dispatcharr-hookdb-2a3
```

- [ ] **Step 6: Write the PR description**

Include, verbatim, all six per-file figures (three baseline runs and three branch runs, missing statements, for both named files), **the tracer core the script used**, the denominator, the three test-time figures against the branch point's, and the guard's pinned/owed line. Give the coverage result as the *direction* the gate asks for — "strictly fewer in every paired run" — not as a percentage anyone downstream could mistake for a target. State the test-time overrun against the stage's ≤ 15 s ceiling plainly rather than omitting it — 2a-2 spent ≈ 3.96 s and this PR spends ≈ 10.9 s. The ceiling has since been withdrawn; record the figure anyway so whoever sets its replacement has it.

Do not push and do not open the PR unless the orchestrator asks.

---

## Self-review

**Spec coverage.** The `2a-3` row of § The seven PRs asks for "tests against `output/ts/generator.py` and `services/channel_service.py`'s switch/stop paths, using the harness; closes matrix rows 7-10, 13", gated on a measured increase on those two files and on the five rows carrying accepted test references. Task 5 states that gate **relatively** — strictly fewer missed statements than a same-session baseline under the same tracer core — because an absolute figure has been invalidated three times during this stage.

- `output/ts/generator.py`: fewer missed statements in every paired run (illustratively 119 → 96 under `sysmon`). Reached through `_setup_streaming`'s time-based positioning (Task 4), `_check_resources`'s channel-stop, channel-state, client-stop and client-gone branches (Tasks 2 and 3), `_process_chunks`'s throttled stats and TTL refresh (every test that streams for over a second), and the expired-chunk jump (Task 2's fourth client). **Not** `_setup_streaming`'s own fallbacks at `:271-292`: those need `find_chunk_index_by_time` to return `None`, and it never does here — its internal `zrange` fallback answers with the oldest chunk instead, which is why every `INFO` log in these tests reads `Time-based positioning: 5s behind -> index 0` rather than one of the fallback messages.
- `services/channel_service.py`: fewer missed statements in every paired run (illustratively 169 → 145 under `sysmon`). `change_stream_url`'s owner branch, `_update_channel_metadata` and `_publish_stream_switch_event` (Task 4); `stop_client` and `stop_channel` (Task 2).
- Rows 7, 8, 9, 13 lose their `owed: 2a-3` markers; row 10 gains a harness pin beside its two e2e ones. The guard prints `9 pinned, 17 owed, 2 white-box-only`.
- Composition rule: every assertion is on a delivered byte, an HTTP status, a JSON field or the fake upstream's connection count. No test patches a relay internal; the only `patch.object` calls target `TSConfig` class attributes, which is the production configuration lever.

**Per-task sequencing.** Walking the tasks in order, holding the set of symbols that exist: Task 1 defines the module and `SOURCE_PID` using only 2a-2 names. Task 2 defines `control.py` (importing only 2a-2 names plus `apps.proxy.internal_auth`) and adds `ClientSetTests`, which uses `ControlMixin`, `nginx_headers` and `open_tune` — all defined in the same task, one step earlier. Task 3 adds `GhostClientTests`, using `ControlMixin` and `open_tune` (Task 2), `SOURCE_PID` and `assert_ts_aligned` (Task 1), and `TS_PACKET_SIZE` (imported in Task 1). Task 4's module imports `ControlMixin` and `open_tune` from Task 2 and nothing from Tasks 1 or 3. Task 5 defines nothing. No task uses a symbol a later task defines.

**Placeholders.** None: every code step carries complete source, every matrix edit carries the exact old and new cell text, and every command carries its expected output.

**Type and name consistency.** `status()` returns `(int, dict)` and every call site unpacks two values. `open_tune()` returns `(Response, _TunedStream)` and every call site unpacks two, discarding the response where it is not needed. `stop_channel_over_http` is named so it cannot be confused with `RelayHarnessTestCase.stop_channel`, which every test also calls. `stop_client` on the mixin does not collide with anything on `RelayHarnessTestCase`. Test method names are unique across both modules, which the parity guard requires since it resolves a `.py` reference by searching for `def <name>(`.

**Negative-scope claims re-checked after the last task was written.** No production file is touched by any task. No existing `harness/` file is edited except `README.md`, in Task 2. `e2e/tests/guards/parity-matrix.ts` is untouched, which stays true because no task adds or removes a row. `e2e/COVERAGE.md` and `metrics/curated/**` are untouched, which stays true because no Playwright test and no ledger item is involved. `CLAUDE.md` is touched in Task 3 only, one sentence, and the plan says explicitly which other stale sentence in the same file is deliberately left alone.
