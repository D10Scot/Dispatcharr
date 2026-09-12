# Phase 2 PR 2b-4 — measured per-file reachability for Gate 2

**Measured 2026-09-12 at `93900a6f`** (main, tip = 2b-1, `contract(phase2): 2b-1 — names and
profiles on next-source and advance (#256)`), in the shape the gate is enforced in:
one Django test label per container, `COVERAGE_CORE=sysmon`, `scripts/coverage_live_path.sh`.

This document exists because the 2b-4 row of the Stage 2b PR table
(`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md:1660`) requires the PR to be scoped
from *a measured per-file reachability pass, not an estimate*. Everything below labelled
**measured** comes from a run recorded here. Everything labelled **estimate** or **inferred** is
reasoning on top of a measurement, and says so in the sentence that makes the claim.

---

## 0. Read this first — five things the brief and the spec get wrong at this commit

**Two of these are figures quoted verbatim in the spec and will otherwise be copied forward:
`1,595` permitted missing (now **1,602**, item 2) and `server.py`'s "222 unreachable or must not be
targeted" (now **139**, item 5).**

1. **The denominator has already moved: 7,978 → 8,011 statements.** The floor file still records
   `statements=7978`; 2b-1 added 33 statements to modules already in scope. This is expected and
   harmless — the floor's own header says `statements` is recorded provenance and is **not**
   compared — but every "N of 7,978" figure in the spec and in the 2b-4 brief is stale arithmetic.
   Confirmed independently by CI: the `coverage-gate` job on run
   [34620721322](https://github.com/D10Scot/Dispatcharr/actions/runs/34620721322) printed
   `denominator: floor 7978 statements  this run 8011 statements`.

2. **"1,595 missing" is no longer what ≥80% means.** 1,595 was `7978 − ceil(0.8 × 7978)`.
   At 8,011 statements, ≥80% permits **1,602** missing. The two differ by 7, and the denominator
   will move again in 2b-2. **2b-4 should compute its floor from the denominator it measures, not
   copy 1,595.** D7's requirement is the ≥80% *threshold*; 1,595 was only ever its arithmetic at a
   particular tree. Both figures appear below where the difference matters.

3. **Stage 2a did not end at 74.30% on today's tree — the tree is at ~75.1%, and 2b-1 already paid
   part of 2b-4's bill.** CI at `93900a6f` measured `missing=1995  coverage 75.10%`. The floor is
   still 2,050 because a PR does not lower it automatically.

4. **The floor's flappy-region list has four entries, not three.** The brief names three; the floor
   file's own header (`scripts/coverage_live_path.floor`, "Four regions are known to flap") adds
   `_wait_for_channel_ready`'s error branch. Re-measured in § 5 — **three of the four do not flap on
   this tree**, both survivors are in `server.py`, and a region on nobody's list does flap.

5. **`server.py`'s "222 unreachable or must not be targeted" is 139 today.** The spec's two figures
   have diverged in opposite directions: `_cleanup_local_resources` is **still exactly 61** (the
   unreachability call was right and nothing has touched it), while `cleanup_task` is **78, not
   161** — stage 2a's tests covered half of it incidentally, though it remains both forbidden to
   target and the largest single source of run-to-run flap. This is not cosmetic: 222 is the figure
   that made the five-biggest-files strategy look 100 statements short of the gate.

---

## 1. How this was measured

Three containers, one per Django label, bind-mounted read-only at this worktree:

```
DISPATCHARR_TEST_CONTAINER=dispatcharr-m2b4-{proxy,liveproxy,channels} \
DISPATCHARR_TEST_DB_VOLUME=dispatcharr-m2b4-db-{proxy,liveproxy,channels} \
  bash .claude/hooks/start-test-container.sh
```

Each round, per container (this is exactly what `scripts/coverage_live_path_isolated.sh` does; the
only difference is that this driver records a label's exit status instead of aborting the round on
it — see § 6):

```
docker exec <container> bash -lc 'export PATH=/dispatcharrpy/bin:$PATH;
  export DJANGO_SECRET_KEY=hook-test-secret; cd /repo &&
  rm -rf /tmp/rd && COVERAGE_LIVE_PATH_DATA_DIR=/tmp/rd \
  bash scripts/coverage_live_path.sh --label <label>'
```

then all three data dirs gathered and combined in one container with
`bash scripts/coverage_live_path.sh --report /tmp/combined`, and
`live-path.json` (coverage's own per-file `missing_lines`) copied out per round.

**13 rounds.** `COVERAGE_CORE=sysmon` is exported by `coverage_live_path.sh` itself
(`scripts/coverage_live_path.sh:58`), so the shape stamp is `per-container/v1-sysmon` — the same
string the floor records. Every round reported `statements 8011`.

### Round-by-round totals (measured)

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| missing | 1997 | 1991 | 2001 | 1996 | 2001 | 2003 | 2003 | 1988 | 1999 | 1969 | 1986 | 1993 | **2022** |

`min=1969  max=2022  spread=53  n=13`. Median 1996.

**The single CI round at this SHA measured 1995** — within 1 of the local median. The local
*distribution* is therefore a usable proxy for CI's, but the local maximum (2022) is 27 above CI's
one sample, and 2a-7's own history is that a local census understated CI by 6. **I did not run a
12-round CI census and cannot claim one.** § 4 plans against 2022 for that reason.

---

## 2. Per-file table (measured, 13 rounds)

`always-miss` = statements missing in **every** one of the 13 rounds — the plannable pool.
`flappy` = missing in some rounds and not others (§ 5). `worst %` = coverage if every flappy line
is missed. Sorted by total missing descending. The 15 fully-covered modules
(`relay_serializers.py`, `relay_views.py`, `constants.py`, `redis_keys.py`, `internal_auth.py`,
`internal_base_url.py`, `permissions.py`, `urls.py`, and the seven empty `__init__.py`) are omitted.

| file | stmts | always-miss | flappy | worst % |
|---|---:|---:|---:|---:|
| `apps/proxy/live_proxy/server.py` | 1492 | 546 | 64 | 59.1% |
| `apps/proxy/live_proxy/input/manager.py` | 1268 | 366 | 20 | 69.6% |
| `apps/proxy/live_proxy/views.py` | 613 | 157 | 0 | 74.4% |
| `apps/proxy/live_proxy/services/channel_service.py` | 505 | 126 | 0 | 75.0% |
| `apps/proxy/live_proxy/output/fmp4/manager.py` | 304 | 97 | 2 | 67.4% |
| `apps/proxy/live_proxy/input/buffer.py` | 248 | 81 | 4 | 65.7% |
| `apps/proxy/live_proxy/output/ts/generator.py` | 377 | 73 | 6 | 79.0% |
| `apps/proxy/live_proxy/services/log_parsers.py` | 235 | 73 | 0 | 68.9% |
| `apps/proxy/next_source.py` | 329 | 59 | 1 | 81.8% |
| `apps/proxy/live_proxy/output/profile/manager.py` | 223 | 58 | 3 | 72.6% |
| `apps/proxy/live_proxy/client_manager.py` | 262 | 52 | 0 | 80.2% |
| `apps/proxy/live_proxy/url_utils.py` | 104 | 47 | 0 | 54.8% |
| `apps/proxy/live_proxy/output/fmp4/generator.py` | 219 | 44 | 5 | 77.6% |
| `apps/proxy/live_proxy/channel_status.py` | 378 | 43 | 0 | 88.6% |
| `apps/proxy/live_proxy/utils.py` | 142 | 32 | 2 | 76.1% |
| `apps/proxy/live_proxy/output/fmp4/buffer.py` | 116 | 26 | 1 | 76.7% |
| `apps/proxy/live_proxy/input/http_streamer.py` | 101 | 21 | 6 | 73.3% |
| `apps/proxy/authorize.py` | 188 | 12 | 0 | 93.6% |
| `apps/proxy/authorize_views.py` | 108 | 4 | 0 | 96.3% |
| `apps/proxy/live_proxy/config_helper.py` | 73 | 4 | 0 | 94.5% |
| `apps/proxy/control_plane.py` | 124 | 3 | 0 | 97.6% |
| `apps/proxy/relay_client.py` | 112 | 3 | 0 | 97.3% |
| `apps/proxy/live_proxy/apps.py` | 10 | 2 | 0 | 80.0% |
| **total (38 modules)** | **8011** | **1929** | **114** | **74.76%** |

---

## 3. The shape of what is left — the single most important finding

**There is no large block left to close. 66% of the remaining gap is in blocks of one to three
statements.** Measured over all 38 modules (round 1; the distribution is stable across rounds):

| contiguous block size | statements | share |
|---|---:|---:|
| 1 | 398 | 19.9% |
| 2–3 | 914 | 45.8% |
| 4–7 | 526 | 26.3% |
| 8–15 | 139 | 7.0% |
| 16+ | 20 | 1.0% |

1,997 missing statements sit in **926 contiguous blocks** — a mean of 2.2 statements per block.
The largest single block in the entire denominator is 20 statements
(`server.py:1172-1191`, inside `handle_client_disconnect`).

**And 683 of 1,997 (34%) are inside `except` handler bodies** (measured by AST: a missing line
inside an `ast.ExceptHandler` span). Per file: `server.py` 146, `input/manager.py` 166,
`views.py` 53, `channel_service.py` 36, `fmp4/manager.py` 32, `profile/manager.py` 28,
`next_source.py` 25, `input/buffer.py` 23, `channel_status.py` 23, `client_manager.py` 21,
`http_streamer.py` 21, `utils.py` 19, `ts/generator.py` 18, `fmp4/buffer.py` 17,
`fmp4/generator.py` 13, `url_utils.py` 14, `log_parsers.py` 12, `authorize.py` 8,
`authorize_views.py` 4, `relay_client.py` 3, `control_plane.py` 1.

**Consequence for planning: closing ~420 statements means provoking roughly 180–200 distinct small
branches.** A plan phrased as "cover file X" will not work; a plan phrased as "for each of these
idioms, one parameterised test" will. Three idioms account for a large fraction of the cheap pool
and each is a *single* test pattern applied repeatedly:

- **`if not self.redis_client: return <X>` guards.** Construct the object with `redis_client = None`
  and call every public method. Present in `client_manager.py` (57, 184, 335, 407, 418-419),
  `channel_status.py` (421), `server.py` (1440-1441, 1455-1456), `channel_service.py` (several).
- **`_execute_redis_command`-style wrappers** with a `(ConnectionError, TimeoutError)` arm and an
  `Exception` arm. Patch the redis client to raise each. `channel_status.py:425-430` (6),
  `client_manager.py:188-193` (6), `server.py:138-159` (14).
- **`except ValueError` around `int(<value from a Redis hash>)`.** Seed the hash with a
  non-numeric value. `channel_status.py` 81-82, 115-116, 494-495, 501-502, 595-596.

---

## 4. Reachability, file by file, for the top contributors

Classification key: **A** = ordinary unit test (may use the real Redis and Postgres the suite
already has); **H** = needs the subprocess harness (`apps/proxy/live_proxy/tests/harness/`) or real
ffmpeg; **U** = structurally unreachable or forbidden.

The `est. A` column is an **estimate** — it is my reading of the uncovered lines, not a measurement
of a test that covered them. The `always-miss` column beside it is measured.

### Tier A — no subprocess, no ffmpeg. This is where 2b-4's statements are.

| file | always-miss | est. A | what is actually in the uncovered lines |
|---|---:|---:|---|
| `services/log_parsers.py` | 73 | ~65 | The **VLC** (`:155+`) and **Streamlink** (`:305+`) parser classes are almost entirely unexercised — `can_parse`, `parse_video_stream`, `parse_audio_stream`, `parse_input_format`. Pure `str → Optional[dict]`: codec maps, `re.search` for `source fps 30/1` and `source 1280x720`, resolution sanity bounds (`100 <= w <= 10000`), the generic-`fps` fallback. **A test is one string literal and one `assertEqual` on a dict.** The spec calls this file "exactly the logic a byte-for-byte port has to get right" (D7's rationale). Highest value per unit of effort in the whole denominator. |
| `url_utils.py` | 47 | ~45 | All 47 are in **one function**, `validate_stream_url` (`:138`). It is plain `requests`: the `udp://`/`rtp://`/`rtsp://` early return, HEAD success, HEAD raising `RequestException` then GET fallback, a non-2xx GET, `StopIteration` on the first chunk (empty body), and a ~20-entry `valid_content_types` membership check. Reachable by patching `requests.Session` or standing up a `http.server` in-process. Live code — called from `views.py:469` and `:491`. |
| `next_source.py` | 59 | ~55 | ORM-fixture branches, no relay state at all: a `Stream` with no M3U account (`:225`), an account with no default profile (`:231`, `:376-377`), `is_active == False` (`:369-371`), no profile with connection capacity (`:270`), `stream_id is None` (`:276`), the XC credential transform `get_transformed_credentials` → `{base}/live/{u}/{p}/{id}.ts` (`:53-60`), `ordered_stream_ids.index()` raising `ValueError` (`:180-181`), and the `isinstance(channel, Stream)` guard (`:337-338`). Ordinary `TestCase` with model fixtures. **Caveat: 2b-2 edits this file** (§ 7). |
| `channel_service.py` | 126 | ~100 | The spec's own estimate — "~90% reachable by a Django test-client request driving an in-process fake upstream with real Redis" — **is consistent with what I read.** Concentrated in `change_stream_url` (33), `validate_channel_state` (30), `cancel_pending_shutdown` (14), `stop_channels` (7), `_channel_proxy_is_active` (6). Pure Python plus Redis calls; no subprocess. |
| `client_manager.py` | 52 | ~45 | `redis_client = None` guards (6 statements across 5 methods), `_execute_redis_command`'s two arms (`:188-193`, 6), the heartbeat thread's "client no longer in Redis" removal (`:108-110`), `add_client`'s failure rollback (`:301-306`, 6), the non-owner `CLIENT_DISCONNECTED` publish (`:370-383`), `refresh_client_ttl` end to end (`:418-431`, 9), and the ghost-client sweep at `:474-485` (11). |
| `channel_status.py` | 43 | ~40 | Almost all one- and two-line branches over a **seeded metadata hash**: the `total_bytes` byte-formatting ladder (`:143`, `:146-147`, `:149` — 4 statements, one parameterised test), `avg_bitrate > 1000` (`:158`), `duration <= 0` (`:19`), absent metadata (`:33`, `:453`), `output_profile_id` parsing (`:189`), the legacy `transfer_rate_KBps` field (`:209`), `chunk_keys_missing` (`:268`), four `except ValueError` int-parse arms, `_execute_redis_command`'s two arms (`:425-430`), and the `Stream.objects` stream-name fallback (`:72-78` — see § 7, this is 2b-3's business). |
| `views.py` | 157 | ~100 | `_channel_setup_needed` (`:60`, 11 statements, **0 in except**) is a pure function over a Redis metadata hash — STOPPING, ERROR/STOPPED, and the "unknown state but the owner's heartbeat key exists" branch (`:89-94`). Directly callable; six seeded-hash cases close all 11. `stream_ts`'s 89 are the same state machine at view level plus the connection-retry loop (`:348-394`: `remaining_time <= retry_interval` break, the `gevent.sleep` + 25ms back-off, the final attempt at the timeout boundary, and `control_plane.release_source` on the abandoned slot). Reachable with a seeded hash and `generate_stream_url` patched to return `None` then a URL. The remainder is inside the streaming generator's plumbing and is harder. |
| `output/ts/generator.py` | 73 | ~55 | Spec says ~80–85% reachable the same way; consistent with what I read. `_wait_for_initialization` (16) and `_init_wait_abort_reason` (10) are **26 statements with zero `except` lines** — pure decision logic over channel state. Plus `_is_timeout` (7, and note the fMP4 sibling's missing `url_switching` exemption defect lives next door), `_check_resources` (9), `_stream_data_generator` (10), `_setup_streaming` (6). |
| `authorize.py` 12, `authorize_views.py` 4, `config_helper.py` 4, `control_plane.py` 3, `relay_client.py` 3, `apps.py` 2 | 28 | ~24 | Small error arms in already-96%+ modules. Cheap, and they are the modules a Go port must match exactly. |
| **Tier A total** | **664** | **~529** | |

### Tier B — needs the subprocess harness or real ffmpeg

| file | always-miss | why |
|---|---:|---|
| `input/manager.py` | 366 | `run` (56, 27 in except), `_attempt_reconnect` (37), `fetch_chunk` (30, 25 in except), `_close_socket` (23, 18 in except), `_read_stderr` (22), `_wait_for_existing_processes_to_close` (18, **0 in except**), `_parse_ffmpeg_stats` (15), `stop` (15). The socket/reconnect arms are mockable; the `run`/`_read_stderr` paths are what the 2a-2 harness exists for. `_wait_for_existing_processes_to_close` (18, no except) is the cheapest block here and is pure polling logic. |
| `output/fmp4/manager.py` | 97 | `_handle_bsf_error` (`:382`) alone is 34: kill the process, join reader/writer threads, respawn via `posix_spawn_proc(FFMPEG_REMUX_CMD_NO_BSF)`, restart three threads. Drivable by patching `posix_spawn_proc` and feeding `_stderr_loop` the non-AAC trigger line, or through the harness. Plus `_stderr_loop` (12), `_writer_loop` (10), `_reader_loop` (10). |
| `output/profile/manager.py` | 58 | The Output Profile ffmpeg cluster — `start`/`stop`/`_writer_loop`/`_reader_loop`/`_stderr_loop`/owner-lock. Spawns; harness territory. |
| `input/buffer.py` | 81 | 47 of them in `get_chunks` (`:170`) alone. The ring buffer is already driven by the harness since 2a-3, so these are its edge branches (wrap-around, missing chunk keys, client-position recovery) rather than its main path. |
| `output/fmp4/generator.py` 44, `output/fmp4/buffer.py` 26 | 70 | fMP4 output format end to end. Needs a tune with `X-Relay-Output-Format: fmp4`. |
| `input/http_streamer.py` | 21 | The **Proxy** stream profile (raw HTTP into the ring buffer, no subprocess). Needs an HTTP upstream stand-in, not ffmpeg — arguably Tier A with an in-process `http.server`. |
| `server.py` `ensure_output_profile` (44) + `ensure_output_format` (22) | 66 | Mixed. The **non-owner** arms (`:1440-1453`, `:1461-1477`) need only a seeded `output_state`/`output_owner` key and a real Redis — `manager.start()` there deliberately fails to acquire the lock and never spawns. The owner arms spawn. |
| **Tier B total** | **~759** | |

### Tier C — unreachable, or forbidden to target

| item | statements | verdict |
|---|---:|---|
| `server.py` `cleanup_task` (`:1884`) | 78 | **Forbidden.** The spec (§ Reachability) is explicit: it ticks on its own interval and samples channels mid-shutdown; chasing it damages the measurement while appearing to improve it. **Re-measured: it was 161 missing when the spec was written and is 78 now** — 2a work halved it incidentally. It is also still the single biggest source of flap (§ 5). |
| `server.py` `_cleanup_local_resources` (`:2491`) | 61 | **Unreachable** — [#230](https://github.com/D10Scot/Dispatcharr/issues/230); the non-owner arm sits under `if self.am_i_owner(...)`. **Re-measured: still exactly 61, unchanged from the spec's figure.** |
| `input/manager.py` `_attempt_health_recovery` (`:1678`) | 14 | **Dead.** `grep -rn "_attempt_health_recovery" --include='*.py'` returns the `def` and nothing else. Already on `CLAUDE.md`'s dead-or-unwired list. |
| `output/fmp4/manager.py:405-413` | ~7 | `if not self.running:` immediately after `self.running = True` at `:403`. Only reachable if `stop()` runs between the two lines. Provoking it means racing a greenlet; the honest classification is defensive-unreachable. |
| **Tier C total** | **~160** | |

Tier A (664) + Tier B (759) + Tier C (160) + the ~346 in `server.py` outside the three named
functions (`event_listener` 69, `initialize_channel` 51, `handle_client_disconnect` 47,
`_check_orphaned_metadata` 23, and ~150 more scattered across 30 small methods) = 1,929.

### On `exclude_lines`

For Tier C the honest answer is **either delete the code or leave it counted**, not an
`exclude_lines` entry. But the arithmetic is worth stating because it is not obvious:

**Deleting D always-missing statements buys ≈ 0.8 D of shortfall**, because the denominator shrinks
too: `shortfall(D) = (2022 − D) − ((8011 − D) − ceil(0.8 × (8011 − D))) ≈ 420 − 0.8 D`.
Deleting `_cleanup_local_resources` (61) and `_attempt_health_recovery` (14) would therefore buy
**60 of the 420** — real, but at 0.8 on the statement, and D5 plus the spec both hand dead-code
deletion to 2d, not to 2b-4. An `exclude_lines` entry has the identical numeric effect *and* moves
`rcfile=` in the floor file, which is an equality check — so it is a deliberate, documented
re-baseline (`--write-floor --shape-only` if `missing` is unchanged, per the floor's own
"HOW TO MOVE THIS FLOOR"), never a free win. **My recommendation is that 2b-4 use neither lever**:
Tier A alone is large enough (§ 6), and a coverage PR that reaches its number by changing the
measurement's definition is exactly what the `rcfile=` hash was added to catch.

---

## 5. The flappy regions, re-measured

Method: intersect the `missing_lines` set across all 13 rounds (lines missing in *every* round are
stable); the symmetric difference against the union is the flappy set. This is the method the floor
file's own gate message prescribes — diff the sets, never difference the totals.

**114 lines flap across 13 rounds; 1,929 are missing in every round.** By file:

| file | flappy lines | ranges |
|---|---:|---|
| `server.py` | 64 | 597, 1263-1264, 1806-1807, 1940, 1961-1967, 1972-1975, 1980, 1982-1983, 1989, 2014-2016, 2021-2022, 2024-2028, 2032, 2034, 2036-2037, 2042-2043, 2045-2046, 2103, 2105-2106, 2112-2116, 2274-2275, 2288, 2493-2495, 2499-2500, 2503-2504, 2506-2507, 2509, 2518, 2527, 2566, 2570 |
| `input/manager.py` | 20 | 363-365, 640-641, 869, 1239-1241, 1243-1245, 1383-1384, 1856-1858, 1861-1863 |
| `output/ts/generator.py` | 6 | 345-346, 351, 440-441, 626 |
| `input/http_streamer.py` | 6 | 153-157, 161 |
| `output/fmp4/generator.py` | 5 | 131, 375-376, 378-379 |
| `input/buffer.py` | 4 | 282, 355-356, 452 |
| `output/profile/manager.py` | 3 | 280, 282, 382 |
| `output/fmp4/manager.py` | 2 | 175-176 |
| `live_proxy/utils.py` | 2 | 221-222 |
| `next_source.py` | 1 | 883 |
| `output/fmp4/buffer.py` | 1 | 92 |

That is 56% of the flap in `server.py`, matching the CI census recorded in the floor file
(92 flappy lines over 6 CI rounds, 64 of them in `server.py`).

### Against the four named regions

| region named in the floor / `CLAUDE.md` | verdict at `93900a6f` |
|---|---|
| **Owner-side coordinated stop — `channel_service.py:28-49`** | **No longer flaps. Zero flappy lines over 13 rounds.** 4 statements (the `except` arm at `:47-49` plus its `return False`) are missing in every round; the rest is covered in every round. Consistent with `coverage_live_path_isolated.sh`'s own claim that per-container isolation makes this block deterministic. |
| **Owner-side coordinated stop — `server.py`'s sweep (`cleanup_task`)** | **Still flaps, and it is now the largest flappy region in the tree**: `1940`, `1961-1967`, `1972-1975`, `1980`, `1982-1983`, `1989`, `2014-2046` — ~35 of the 64 `server.py` lines. This is the region the spec forbids targeting. |
| **Non-owner local cleanup — `server.py:2099-2112` and `2489-2566`** | **Still flaps**, 17 lines across the two spans (`2103`, `2105-2106`, `2112-2116`; `2493-2495`, `2499-2500`, `2503-2504`, `2506-2507`, `2509`, `2518`, `2527`, `2566`). 48 statements in the two spans are missing in every round. |
| **stderr-reader join — `input/manager.py:1739-1767`** | **No longer flaps. Zero flappy lines over 13 rounds**; 10 statements in the span are missing in every round, 19 lines covered in every round. |
| **`_wait_for_channel_ready`'s error branch** (the floor's fourth region) — `output/ts/generator.py:227-230`, per `docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md:116` | **Does not flap. Missing in all 13 rounds**, along with `:234-235`. The 2a-7 plan predicted it would flap on trees carrying 2a-6's tests, and `main` carries them — **it does not flap here**, so on this tree it is stable headroom rather than variance. These 6 statements are part of `_wait_for_initialization`'s 16 in § 4's Tier A row for that file. Note the name also exists on `fmp4/generator.py:140`, whose own `:154-168` are likewise missing in all 13 rounds; the floor's region is the `ts` one. |

So **two of the four documented regions no longer flap at all** (the `channel_service.py` coordinated stop and the `input/manager.py` stderr-reader join), a third never did on this tree
(`_wait_for_channel_ready`), and the two that remain are both in `server.py`.

**Two regions not on anybody's list that do flap:** `server.py:2014-2046` (~18 lines, inside
`cleanup_task`) and `input/http_streamer.py:153-161` (6 of that file's 27 missing).

**Planning consequence:** none of the 114 flappy lines should be counted as available headroom.
The plannable pool is the 1,929 always-missing set, and every figure in § 2's `always-miss` column
and § 4 is drawn from it.

---

## 6. Recommended scope for 2b-4

### The arithmetic

**Note (added 2026-09-12):** the `utils.py` question in the right-hand column has since been ruled
on — § 8. The ruling relocates `_live_connections` only, which is a **third** variant costing −1;
the "with `apps/proxy/utils.py`" column below is the rejected option, kept because it is the
comparison that decided it.

| | without `apps/proxy/utils.py` | with `apps/proxy/utils.py` |
|---|---:|---:|
| denominator (measured) | 8,011 | 8,271 |
| missing, worst of 13 local rounds (measured) | 2,022 | 2,110 |
| missing, the one CI round at this SHA (measured) | 1,995 | — |
| covered needed for ≥80% | 6,409 | 6,617 |
| **missing permitted at ≥80%** | **1,602** | **1,654** |
| missing permitted by the brief's literal 1,595 | 1,595 | — |
| **shortfall from the local worst case** | **420** | **456** |
| shortfall from the CI sample | 393 | — |

**Plan against 420, not 393**, and treat 1,602 as the target with 1,595 as the safer number to
write into the floor if the denominator has not moved by then. The floor must be the worst of a
≥12-round **CI** census (the floor file's own procedure, steps 1–2), and I have one CI sample.

### Recommended order

All Tier A. No subprocess harness, no real ffmpeg, no `exclude_lines`, no dead-code deletion.
`est. avail.` is the § 4 estimate; `always-miss` is measured.

| # | file | always-miss | est. avail. | cumulative est. | why here |
|---|---|---:|---:|---:|---|
| 1 | `services/log_parsers.py` | 73 | 65 | 65 | Pure string→dict. Cheapest statements in the tree, and D7's own stated rationale for Gate 2. |
| 2 | `next_source.py` | 59 | 55 | 120 | ORM fixtures only. **Sequence this before or with 2b-2**, which edits the file. |
| 3 | `url_utils.py` | 47 | 45 | 165 | One function, `requests` mocking. |
| 4 | `channel_status.py` | 43 | 40 | 205 | Seeded metadata hash; three parameterised tests cover most of it. Overlaps 2b-3 at `:72-78`. |
| 5 | `client_manager.py` | 52 | 45 | 250 | The three idioms in § 3, concentrated. |
| 6 | `services/channel_service.py` | 126 | 100 | 350 | Largest Tier A pool; spec's own ~90% estimate held up on inspection. |
| 7 | `output/ts/generator.py` | 73 | 55 | 405 | `_wait_for_initialization` + `_init_wait_abort_reason` = 26 with no `except` lines. |
| 8 | boundary smalls (`authorize`, `authorize_views`, `config_helper`, `control_plane`, `relay_client`, `apps`) | 28 | 24 | **429** | Cheap, and they are the modules the Go port must match byte for byte. |
| — | **reserve:** `views.py` | 157 | 100 | 529 | `_channel_setup_needed` (11, pure) first; `stream_ts`'s state branches next. Draw on this only if 1–8 undershoot. |

**429 estimated against a 420 shortfall is not enough margin on its own** — that is a 2% cushion on
a set of numbers whose history in this programme is to come in low. Take items 1–8 **and**
`views.py`'s `_channel_setup_needed` plus the `stream_ts` state machine (~60 more) as the working
scope: ~490 estimated against 420 needed, a 17% cushion. Items 1–5 are small, independent files and
make natural early commits; 6 and 7 are where the work concentrates.

### Confidence

**Moderate-to-high on the pool, moderate on the conversion rate.**

- The `always-miss` column is measured over 13 rounds and I would be surprised by more than ±5 per
  file. High confidence.
- The `est. avail.` column is my reading of the uncovered lines, not a demonstration. **Historically
  in this programme, reachability estimates have come in optimistic** — this is the explicit reason
  the 2b-4 row demands a measured pass. Discount it accordingly; the 17% cushion above is that
  discount.
- The 420 figure rests on a local worst-of-13 standing in for a CI worst-of-12. If CI's spread at
  this tree is wider than local's 53, 420 is low.

### What would change the answer

1. **A 12-round CI census at the 2b-4 branch point.** If CI's worst comes in above 2022, the
   shortfall grows one-for-one. This is the single highest-value thing to do before finalising scope.
2. **2b-2 landing.** It adds contract code to `next_source.py`, `authorize_views.py` and
   `internal_auth.py`. New statements arrive **uncovered unless 2b-2 tests them**, and each
   uncovered new statement costs ~0.2 of shortfall net (it raises both the numerator and the
   permitted ceiling). If 2b-2 ships its own tests, it is shortfall-neutral or better.
3. **2b-3 deleting `channel_status.py:72-78`** (§ 7) — worth ~5.6 of shortfall, and it removes 7
   statements from item 4's pool.
4. **The `_live_connections` relocation, now ruled in and carried by 2b-4** (§ 8). It is
   shortfall-neutral (420 → 419) but it **does** move the denominator to 8,039 and the permitted
   ceiling to 1,607, so **every figure in this section is a pre-move figure**. Do the move first,
   re-measure, then fix scope.
5. **Any decision to delete Tier C.** 75 statements of dead code ≈ 60 of shortfall, at 0.8 on the
   statement. Not recommended for 2b-4, but it is the one lever that would make 420 comfortable.

---

## 7. Caveat 1 — this is a baseline at `93900a6f`; 2b-2 and 2b-3 land first

**Every per-file number above must be re-measured after 2b-2 and 2b-3 merge.** Specifically:

- **2b-2** (`OutputProfile.build_command()` folded into `next-source`; `X-Relay-Output-Format` and
  `X-Relay-Client-IP` end to end) edits **`next_source.py`** (item 2 in the recommended order),
  **`authorize_views.py`** and **`internal_auth.py`** (item 8). It will move both the denominator
  and item 2's pool. Sequence item 2 after 2b-2, or expect to redo it.
- **2b-3** deletes whichever of `channel_status.py`'s two ORM fallbacks prove unreachable.
  **Measured input for that decision, which 2b-3 should have:**
  - The **`Stream.objects` stream-name fallback at `:72-78`** (7 statements) is missing in **all 13
    rounds** — nothing in the suite reaches it. Deletion candidate.
  - The **`M3UAccountProfile.objects` fallback body at `:103-110`** is **covered in every round**;
    only its `except (ImportError, DatabaseError)` arm at `:111-112` is missing. It is reachable, so
    it is an allowlist entry, not a deletion.

  Deleting `:72-78` removes 7 always-missing statements from item 4's pool and buys ~5.6 of shortfall.
- 2b-1 has already moved the denominator once (7,978 → 8,011). Expect the same from 2b-2.

---

## 8. The `apps/proxy/utils.py` denominator question — measured here, and **decided**

> ### DECISION (user ruling, 2026-09-12): relocate `_live_connections` to a boundary module so it joins the gate denominator. **Carried in 2b-4** — not a separate PR, and not deferred to 2c.
>
> The question had been carried unresolved since stage 2a; the measurements in this section are what
> closed it. Recorded here so 2b-4's planner does not re-derive or re-litigate it.
>
> **Rationale.** Relocation *dominates* on the arithmetic — shortfall 420 → **419**, one statement
> better, against **+36** for including the whole file — and it brings the tune-path relay call
> (`relay_client.list_channels(all_clients=True, timeout=TUNE_TIMEOUT)` plus its
> `RelayUnavailable`/`RelayRefused` and `ImproperlyConfigured` arms) inside the gate that guards the
> Go port, which is the kind of boundary code Gate 2 exists for. Folding it into 2b-4 rather than a
> separate PR means **one** `--write-floor --shape-only` re-baseline instead of two, and no extra CI
> cycle under the fully-sequential merge order.
>
> **Three consequences that must travel with the decision:**
>
> 1. **This is a code move, not a floor edit.** `_live_connections` has to physically leave
>    `apps/proxy/utils.py` for a module the rcfile's `[report] include` names. Editing the rcfile to
>    pull the function's *file* into scope is the other option, and it is the one that was rejected
>    (+36). The move belongs to whichever PR is willing to touch `utils.py`, and by this ruling that
>    is **2b-4**.
> 2. **It changes `modules=`, which is an equality check**, so 2b-4 must run a deliberate
>    `scripts/coverage_live_path.sh --write-floor --shape-only` re-baseline alongside its `missing`
>    move. **This is the declined-override machinery being used exactly as designed, not a
>    workaround** — `coverage_live_path.floor`'s own "HOW TO MOVE THIS FLOOR" describes precisely
>    this case, and `--shape-only` exists so a module-list change cannot silently overwrite a
>    campaign's `missing`/`runs` provenance. A later reader finding a shape-only re-baseline in the
>    same PR as a floor move should **not** read it as someone dodging the ratchet.
> 3. **Ordering: re-measure after the move, not before.** The relocation changes the denominator
>    (8,011 → 8,039) and therefore both the permitted-missing ceiling and the shortfall. **The ~420
>    shortfall and the per-file pool in § 2 and § 6 are pre-move figures.** A plan that relocates and
>    then spends exactly the 429 statements of a pool measured before the move is working from a
>    stale denominator — the same error class as carrying 1,595 forward past a denominator that had
>    already moved to 8,011 (§ 0, items 1-2). Relocate first, re-measure, then scope.

Both variants,
measured at `93900a6f` over the worst local round (13), by re-running `coverage report` against the
same combined data with `apps/proxy/utils.py` added to the rcfile's `[report] include`:

```
docker exec dispatcharr-m2b4-proxy bash -lc 'python -m coverage report --rcfile=/tmp/rc_with_utils.coveragerc'
  apps/proxy/utils.py    260   88   66%
  TOTAL                 8271 2110   74%
```

| variant | stmts | missing | permitted at ≥80% | shortfall |
|---|---:|---:|---:|---:|
| as today (utils.py **out**) | 8,011 | 2,022 | 1,602 | **420** |
| utils.py **in** | 8,271 | 2,110 | 1,654 | **456** |
| only `_live_connections` relocated to a boundary module | 8,039 | 2,026 | 1,607 | **419** |

- **Including all of `utils.py` costs a net +36 statements of shortfall** (88 newly-counted missing
  against +52 of permitted headroom). The brief's estimate of +38 was close; the measured figure at
  this commit is **+36**, on 260 statements / 88 missed (the brief said 90 missed).
- **The sharper alternative is shortfall-neutral.** `_live_connections` (`apps/proxy/utils.py:256-321`)
  is **28 statements with 4 missing** (85.7% covered — it already has three dedicated tests in
  `apps/proxy/tests/test_stream_limits.py`). Relocating it to a boundary module moves the shortfall
  from 420 to **419** — one statement *better* — while bringing the tune-path relay call
  (`relay_client.list_channels(all_clients=True, timeout=TUNE_TIMEOUT)`, its `RelayUnavailable`/
  `RelayRefused` arm and its `ImproperlyConfigured` arm) inside the gate that guards the Go port.
- Relocating changes `modules=` in the floor file, which is an equality check — a deliberate
  `--write-floor --shape-only` re-baseline, not a free move. Including all of `utils.py` changes
  both `modules=` and the shortfall.

**On the numbers, relocating `_live_connections` dominates including the whole file**: it costs
nothing, and it puts the only part of `utils.py` that is on the relay boundary into scope. That was
an observation about the arithmetic when first written; it is now the ruling at the head of this
section.

---

## 9. Two things that surprised me, recorded because they cost time

1. **`apps.proxy.live_proxy.tests.test_manager_stderr_failover.FfmpegStderrFailoverTests.test_a_buffering_threshold_change_does_not_reach_a_running_channel`
   fails in 9 of 13 local rounds and passes in CI.** The failing assertion is
   `assertGreaterEqual(len(seen), 4, "too few distinct speeds after the change to prove records
   were still being parsed")` — observed `3` (e.g. `[3.05, 3.25, 3.42]`). That is the test's
   **falsifiability guard**, not the property under test; the property (a running channel does not
   pick up the new `buffering_speed`) passed every time. It is sampling-rate sensitive and Docker
   Desktop on macOS is slower than the CI runner. **Measured impact on coverage: none** — the four
   rounds where the label passed (2, 5, 6, 11) produced 1991, 2001, 2003, 1986, squarely inside the
   range of the nine that failed. A narrower fix than loosening the bound would be to raise
   `chunks=24` or slow `stderr_interval`, so the guard counts records rather than wall-clock luck.

   **This matters for 2b-4 beyond the noise**: `scripts/coverage_live_path_isolated.sh` runs under
   `set -euo pipefail`, so a single flaky assertion **aborts the round before the `channels` label
   runs** — the first thing I tried produced no measurement at all. Anyone re-measuring locally
   should expect that and either fix the test or drive the labels with a wrapper that records
   status instead of aborting.

2. **The spec's two `server.py` "do not target" figures have diverged in opposite ways, and both are
   worth knowing.** `_cleanup_local_resources` is **still exactly 61** missing — the unreachability
   call in the spec was right and nothing has touched it. But `cleanup_task` is **78, not 161** —
   stage 2a's tests covered half of it incidentally, while it remains both forbidden to target and
   the single largest source of run-to-run flap. The spec's "222 unreachable or must not be
   targeted" in `server.py` is therefore **139** today.
