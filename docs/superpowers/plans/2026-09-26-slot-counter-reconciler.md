# Plan: the provider-slot counter reconciler (#513, Phase 3 close-out D1)

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Each PR's code is Appendix A, B or C, a byte-exact `git diff` verified to apply in order at the seed; the tasks around it are the checks that prove it landed.

**Goal.** `profile_connections:{id}` and `server_group_connections:{group}:{fp}` stop drifting in either direction. Every write to them moves through one Lua script that bumps a per-counter version, and a beat task recomputes each counter from who actually holds a provider connection. It writes only where the version has not moved since its previous run, and it never lowers a counter below a holder that is merely paused, in flight, or missing from a single run.

**Seed.** `b2d0ff5e2e7ce0fb9e8dfd9a1c30bca2e6f623f3` (`b2d0ff5e`, main on 2026-09-26). Every `file:line` below is at the seed unless it says otherwise. Main has since moved to `02a5fe5c` through two docs-only commits (#504, and #516 for ADR 0007) and #517 (D2, #514). All three appendices apply cleanly there too, and the four labels they share with #517 are green on it (§ What was measured).

**Authority.** In order of precedence:

1. Issue #513. Its seven constraints are binding rulings, and this plan's Decisions section answers each one by number.
2. The review-passed Phase 3 reassessment (the user's `~/git/phase3-reassessment-2026-09-26.md`, § 5 Option D and § 6.1). Its five review rounds are in the companion `-review.md`, and this plan reopens none of their findings.
3. CLAUDE.md, ADR 0005 (slots stay in Django), ADR 0006 (the Go relay keeps its state in memory) and ADR 0007 (Phase 3 is closed; #513 is fix work, not a phase).
4. `CONTEXT.md` is not contradicted: its glossary keeps the provider-slot counters in Redis and in Django (main `:167`, `:193-198`), which is exactly where D1 leaves them.
5. `docs/relay-parity-matrix.md` is not affected: no row covers provider slots, because the Go relay never touches a counter (it asks `next-source` and posts `release`), and D1 changes no externally observable live-path behaviour.

**Issues.** #513 (planned in PR D1-3), #470 (planned in PR D1-1), #471 (planned in PR D1-1). #356 is related and is not fixed here (§ What this plan does not do).

## Global constraints

Every PR carries these. A reviewer checks each one against the PR's diff.

1. **Every write to either counter family is inside `apps/m3u/connection_pool.py`'s `_SLOT_SCRIPT`.** No `INCR`, `DECR`, `SET` or pipeline on a `profile_connections:*` or `server_group_connections:*` key exists anywhere else. The grep in D1-1 Task 3 must print nothing on every PR's head.
2. **No new ORM read on the query ledger's drives.** `apps/proxy/tests/test_tune_path_query_ledger.py` passes unchanged at every stage (measured), and its `LEDGER` is not edited. One read is added outside those drives: a reserve refused `profile_full` on a pooled STD profile now resolves the credential fingerprint first (one `Stream` read; see the table in Constraint 1).
3. **`test_vod_lock_contention.py`'s guarantee is kept byte for byte.** `active_streams` is mutated only by the four existing VOD Lua scripts, outside the session metadata lock. D1's refresher writes only `EXPIRE` and the `worker_id` field on a VOD hash, and the reconciler only reads it. That module is not edited and passes at every stage.
4. **No Gate 2 module is edited.** The nine files in `scripts/coverage_live_path.coveragerc`'s `[report] include` stay untouched, so neither `modules=` nor `rcfile=` moves. `apps/proxy/slot_reconciler.py` is new and sits outside that list. `apps/proxy/control_plane.py`'s timeout constants are imported, not edited.
5. **No new cross-app import edge.** The reconciler lives in `apps/proxy`, which already imports `apps.m3u` (`next_source.py`), `apps.timeshift` (`authorize.py`, `utils.py`, `stats_views.py`) and `apps.channels`. `apps/timeshift/views.py` importing `apps.proxy.vod_proxy.held_records` stays inside the existing `timeshift → proxy` edge. Placing the reconciler in `apps/m3u` instead would have added `m3u → timeshift` and a second import cycle.
6. **The Go relay is not touched.** D1 reads `GET /proxy/relay/channels` through the existing `relay_client.list_channels`, and `relay_client.py` is not edited.
7. **The test-modification rule.** Every existing test that changes is listed with before and after in § Tests. No assertion is loosened, no count lowered, no tolerance widened.
8. **Real Redis for atomicity.** Every test whose property is atomicity or a Redis-side script runs against the live Redis the suite already uses. It skips when Redis is missing, except under `CI`, where it fails instead (the pattern `relay/channel/source_transcode_real_test.go` uses for ffmpeg). CI's `scripts/ci_bootstrap_backend.sh:65-71` starts Redis in every label's job, so each label has one.
9. **Credential logging.** `scripts/check_credential_logging.py` exits 0 on every touched `.py` file (measured). The reconciler never logs a `server_group_connections` key, because its last segment is a prefix of a SHA-256 of the provider login. `_loggable()` prints the server group instead.
10. **The test hooks' shared container.** `PostToolUse` hooks run in `dispatcharr-testrunner`, whatever worktree the implementer holds. Re-point it at the implementer's worktree per CLAUDE.md § Test hooks, or run each label by hand as § What was measured did.

## What was measured

Everything below was run on 2026-09-26 in a detached clone at the seed, `scratchpad/plan-d1/wt`. It used a private container, `d1-plan-runner` (image `ghcr.io/d10scot/dispatcharr:latest` `f089ed52`, the one the shared hook container uses; Redis 8.10.1, PostgreSQL in-container), started by `.claude/hooks/start-test-container.sh` with `DISPATCHARR_TEST_CONTAINER`, `DISPATCHARR_TEST_DB_VOLUME` and `CLAUDE_HOOK_REPO_ROOT` overridden. Every label ran on a fresh test database (`--noinput`, no `--keepdb`), with Redis flushed first and `CI=1` set.

**The seed baseline is green on fresh databases.** Under `--keepdb` the seed shows five failures: three errors in `apps.channels.tests.test_profile_membership_race` and two in `test_tune_path_query_ledger`, which misses a `core_useragent` read. Both modules pass on a fresh database, so these are keepdb artifacts (the memory "keepdb hides seeded-row drift"), not defects. Use fresh databases when measuring this work.

| Label | Seed | + D1-1 | + D1-2 | + D1-3 |
|---|---|---|---|---|
| apps.m3u.tests | 245 | 259 | 259 | 259 |
| apps.channels.tests | 365 | 365 | 365 | 365 |
| apps.proxy.tests | 399 | 399 | 399 | 420 |
| apps.proxy.vod_proxy.tests | 92 | 92 | 104 | 104 |
| apps.timeshift.tests | 451 | 451 | 454 | 454 |
| core.tests | 138 | 138 | 138 | 139 |
| tests | 168 | 169 | 170 | 170 |

The other eight labels (`apps.accounts`, `backups`, `connect`, `dashboard`, `epg`, `output`, `plugins`, `vod`) are unchanged and green at every stage. Every stage selects the full suite through `_SHARED_PATH_PREFIXES`, because each one edits a file under `dispatcharr/`. The full suite was run at each of the three final scratch SHAs.

**The slot script on real Redis.** Probe output, profile cap 2, pooled on credential key `…:7:ffff`:

```
reserve1           (True, 1, None)            counter 1  version 1   cred 1  version 1   pointer set
reserve2           (True, 2, None)            counter 2  version 2   cred 2  version 2
reserve3 refused   (False, 2, 'profile_full') counter 2  version 2   cred 2  version 2   (nothing written)
release            counter 1 v3, cred 1 v3, pointer deleted
release again      counter 0 v4, cred 1 v3   (#356: the pointer is gone, the credential counter is not given back)
reserve from -3/-2 (True, 1, None)            profile 1, cred 1          (#471 and #470 repaired atomically)
release from -4    counter 0, version 2                                  (#471)
unlimited reserve  (True, 0, None)            no key written at all
reconcile, stale version       (-1, 0, 0)     no write
reconcile, in range            (0, 0, 0)      no write
reconcile, out-of-band 4→[1,2] (1, 4, 2)      counter 2, version unchanged at 4
switch refused (new login full)  False        nothing written, pointer unchanged
switch ok                        True         p1 0 v2, p2 1 v1, cred a 0, cred b 1, pointer moved, stream_profile:55 = 2
```

**Round trips and latency.** 2,000 reserve-plus-release pairs over loopback in the container:

| | Reserve | Release | Median | p99 |
|---|---|---|---|---|
| Seed (Python) | 3 round trips | 6 round trips | 454 µs | 610 µs |
| Script | 1 round trip | 1 round trip | 122 µs | 225 µs |

**Every break-check was run.** Each wrong edit was applied alone, and each reddens its named test with the message quoted in the PR sections.

**The appendices were verified.** Each diff was produced with `git diff` between the scratch commits. All three passed `git apply --check --whitespace=error` and then applied in order on a fresh clone at the seed, and the result is byte-identical to the scratch tree (`diff -rq`, excluding `.git`, `__pycache__` and `media`). They also apply in order on main `1b3097e8` and on `02a5fe5c`, the merge of D2's PR #517. On `02a5fe5c` plus all three, in a second private container, `apps.m3u.tests` 259, `apps.proxy.tests` 420, `apps.proxy.vod_proxy.tests` 104 and `apps.timeshift.tests` 458 (D2's four tests added) all pass. The appendices extracted from this document's committed copy rebuild the prototype tree byte for byte.

## Decisions

### Constraint 1: one versioned script, every writer inside it

**The writers at the seed.** This is the enumeration #513 asks for, run first:

```
$ git grep -n -E 'profile_connections|server_group_connections|profile_credential_release|reserve_profile_slot|release_profile_slot|_safe_decr|move_credential_slot_on_profile_switch|_reserve_server_group_slot|_release_credential_slot' b2d0ff5e2e -- ':!*tests*' ':!docs' ':!*.md'
$ git grep -n -E 'redis_client\.(incr|decr|set|delete)\(' b2d0ff5e2e -- apps/m3u/connection_pool.py
$ git grep -n -E '\.(incr|decr|incrby|decrby|set|delete|getset)\(|pipe\.(incr|decr|set)' b2d0ff5e2e -- apps core dispatcharr ':!*tests*' \
    | grep -E 'profile_connections|server_group_connections|profile_key|cred_key|old_profile_connections_key|new_profile_connections_key'
```

These are all the direct writes to either family:

| Site | Write | Fate in D1-1 |
|---|---|---|
| `connection_pool.py:238,240,242` (`_safe_decr`) | SET 0 / DECR / SET 0 | the script's `give_back` |
| `:248` (`_remember_credential_release_key`) | SET pointer | the script's `reserve` and `switch` |
| `:261` (`_release_credential_slot_by_profile_id`) | DEL pointer | the script's `release` and `switch` |
| `:276,280,285` (`_reserve_server_group_slot_for_profile`) | INCR / SET 1 / DECR | the script's `reserve`, which checks both caps before writing either |
| `:302,304,312` (`reserve_profile_slot`) | INCR / DECR / DECR | the script's `reserve` |
| `:332` (`release_profile_slot`) | DECR | the script's `release` |
| `:198-229` (`move_credential_slot_on_profile_switch`) | through the three helpers above | deleted; the script's `switch` |
| `apps/channels/models.py:787-792` (`Channel.update_stream_profile()`) | pipeline DECR / SET / INCR | `switch_profile_slot()` → the script's `switch` |
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py:1604` (`create_connection`) | pipeline INCR | deleted: the method has no caller |
| `:1642` (`remove_connection`) | pipeline DECR | deleted: no caller |
| `:1650-1666` (`update_connection_activity`) | writes only `vod_proxy:connection:*` | deleted with the other two: no caller; that key family has no reader |

Every other site in the first grep reads a counter or calls `reserve_profile_slot`/`release_profile_slot`, whose signatures are unchanged. The read sites are `connection_pool.py:145-182`, `vod_proxy/views.py:554-555`, `mwcm.py:927` and `next_source.py:1132`. The callers are `models.py:247,285,515,610,718`, `mwcm.py:840,926`, `timeshift/views.py:663,1697,2167,2391,2455` and `next_source.py:1132`. The "no callers" claim for the three VOD methods was re-grepped at the seed: `.create_connection(` appears only at `mwcm.py:1015`, which is `RedisBackedVODConnection`'s own method, and `.remove_connection(`, `.update_connection_activity(`, `vod_proxy:connection` and `vod_proxy:content` appear nowhere outside the three methods. After D1-1 the third grep prints nothing (exit 1 under `pipefail`).

**The version key** is `slot_version:<counter key>`: `slot_version:profile_connections:5`, `slot_version:server_group_connections:3:0a1b…`. It is a plain integer string in Redis DB 0 beside its counter, with no TTL, so it lives exactly as long as its counter. The prefix means neither a `profile_connections:*` nor a `server_group_connections:*` SCAN matches it. `slot_version_key()` is the one builder. A Redis restart loses both keys together, and the reconciler's snapshot with them, so no stale version survives its counter.

**The script** is `_SLOT_SCRIPT` in `apps/m3u/connection_pool.py`, one source with four ops dispatched on `ARGV[1]`. `read(k)` is `tonumber(GET k) or 0`. `write(k, v)` is `SET k v` followed by `INCR slot_version:k`, and it is the only way the script writes a counter. The two primitives are built on it:

- `give_back(k)`: a counter above 0 drops by one; a counter below 0 is set to 0 (the #470/#471 repair); 0 or absent is left untouched and bumps nothing.
- `take(k)`: a negative counter counts from 0, then goes up by one.

| Op | KEYS | ARGV | Semantics | Returns |
|---|---|---|---|---|
| `reserve` | profile counter, credential counter (or `provider_slot:unused`), release pointer | op, profile max (0 = not counted), credential max (0 = no credential counter) | Reads both counters, treating a negative as 0. If profile max > 0 and count + 1 > max: refuse `profile_full`. If credential max > 0 and count + 1 > max: refuse `credential_full`. Only then writes both, and sets the pointer to the credential key. **A refusal writes nothing.** | `{1, new profile count or 0, ''}` or `{0, profile count, reason}`; `reserve_profile_slot` maps these to its unchanged `(reserved, count, reason)` tuple |
| `release` | profile counter, release pointer | op | If the pointer names a credential counter, `give_back` it and delete the pointer; then `give_back` the profile counter | 1 if a credential counter was released, else 0 |
| `switch` | old profile counter, new profile counter, `stream_profile:<stream>`, old pointer, new pointer, new credential counter (or `provider_slot:unused`) | op, new profile id, move credential (`1`/`0`), new credential max | If the login changes: check the new login's cap first and refuse `credential_full` with nothing written; else `give_back` the old credential through the old pointer, delete it, and `write` the new one, setting the new pointer. Then `give_back` the old profile counter, `SET` the `stream_profile` key, and `take` the new profile counter | `{1, ''}` or `{0, 'credential_full'}` |
| `reconcile` | counter | op, expected version, floor, ceiling | If the counter's version ≠ expected: no write. Else clamp the counter into [floor, ceiling] with a bare `SET`. **The reconciler bumps no version: it is not a holder.** An absent counter clamped to 0 is not created. | `{-1, c, c}`, `{0, c, c}` or `{1, before, after}` |

`release` reads the credential counter's name from the pointer inside the script, so it touches a key not passed in `KEYS`. That is safe on the single, non-cluster Redis every deployment runs, and it is why a release needs no ORM read. `PoolEnforcementTests.test_release_uses_stored_credential_key_without_db_lookup` pins that, unchanged.

The Python surface is `reserve_profile_slot` and `release_profile_slot` with unchanged signatures, plus four new functions. `switch_profile_slot(old_profile, new_profile, stream_profile_key, redis_client) -> bool` is used by `Channel.update_stream_profile()`. `credential_reservation(profile) -> (key or None, cap)` is the one place that decides whether a profile counts against a credential counter; the reconciler uses it too. `reconcile_counter(key, expected, floor, ceiling, client) -> (status, before, after)` and `read_slot_versions(keys, client) -> {key: int}` round out the set. `_run_slot_script` calls `redis_client.register_script(_SLOT_SCRIPT)` on every call. That only hashes the source; the first call per server loads it and every later call is one `EVALSHA`. It keeps no per-client cache, because a cache keyed on `id(client)` can hand a new client a `Script` bound to a dead one, which is why `test_vod_lock_contention.py` clears `_vod_script_cache` in its own setUp.

**How `update_stream_profile()` is routed** (`models.py:760-792` → one call). It keeps its early returns, the `current_profile_id == new_profile_id` shortcut and both `M3UAccountProfile` reads (the same two reads `move_credential_slot_on_profile_switch` needed). It then calls `switch_profile_slot(old_profile, new_profile, RedisKeys.stream_profile(stream_id), redis_client)`. The credential move, both profile counters and the `stream_profile` key move in one atomic step with versions bumped. The old code released the old credential first and re-reserved it on refusal. The script checks first, so a refused switch now leaves everything exactly as it was, where the old restore could itself be refused and drop the old credential slot. `next_source.py:826` is unchanged.

**What each existing behaviour becomes:**

| Case | Seed | D1-1 |
|---|---|---|
| Reserve, room on both | INCR profile, INCR credential, SET pointer | the same writes, atomic, versions bumped |
| Reserve refused `profile_full` | INCR then DECR (profile) | nothing written; returns the same count |
| Reserve refused `credential_full` | INCR profile, INCR then DECR credential, DECR profile | nothing written |
| Reserve on a counter at −3, cap 1 | profile: admitted at −2 and stays negative (#471); credential: SET 1 (non-atomic, #470) | treated as 0: admitted once, counter 1, then refused |
| Release, counter negative | profile: left negative (#471); credential: GET then SET 0 (non-atomic, #470) | repaired to 0 atomically, version bumped |
| Unlimited profile (`max_streams` 0) | no profile write, no credential write | unchanged |
| Switch onto an unlimited profile | INCR its counter | unchanged: `take` (kept deliberately; see § What this plan does not do) |
| Reserve on a pooled profile already at its own cap | refused before the fingerprint was computed | the fingerprint is resolved first, which costs one `Stream` read for an STD account and none for XC. The ledger's drives are unaffected (measured). |

**#470 and #471.** D1-1 lands the repair for both, pinned against real Redis (§ PR D1-1), so D1-1's PR carries one closing keyword for each. #356 is not repaired here: § Overlap.

### Constraint 2: run spacing derived at run time

`apps/proxy/slot_reconciler.py:in_flight_windows()` returns the longest a reservation can go unseen on each surface, and `run_spacing_seconds()` is:

```
S = max(MIN_SPACING_SECONDS, SPACING_FACTOR × max(W_live, W_vod, W_catch_up))
  = max(60, 2 × max(14.1, 40, 20))   = 80 s at default settings

W_live     = control_plane.ATTEMPTS × (CONNECT_TIMEOUT + READ_TIMEOUT) + RETRY_DELAY
           = 2 × (2 + 5) + 0.1 = 14.1 s       (apps/proxy/control_plane.py:37-41; the same constants
                                               relay/httpapi/stream.go:180's tuneBudget is built from)
W_vod      = UPSTREAM_ATTEMPTS × sum(UPSTREAM_TIMEOUT)
           = 2 × (10 + 10) = 40 s             (mwcm.py:499,518's (10, 10), hoisted to named constants by D1-3)
W_catch_up = POOL_LOCK_WAIT_SECONDS + ConfigHelper.connection_timeout() + ConfigHelper.chunk_timeout()
           = 5 + 10 + 5 = 20 s at defaults    (timeshift/views.py:2137's blocking_timeout=5, hoisted by D1-3;
                                               the two operator-editable settings _open_upstream uses, :3156-3157)
```

- **Why each window.** The relay lists a channel the moment its `next-source` call returns (`relay/channel/manager.go:131-190`'s `Attach`, the map insert at `:302`). `Channel.get_stream()` reserves inside that call, so the live window is that call's budget. VOD reserves at `mwcm.py:992`, before the provider GET at `:1087`, and `active_streams` goes up only when the generator starts (`:1135-1136`). One request can make two GETs (`:514-520`), each up to connect plus first byte.
- **Why catch-up still carries the provider timeouts.** At the seed, catch-up's busy pool entry is written right after the reserve: `_serve_catchup` calls `_create_pool_session` at `views.py:648`, before `_attempt_timeshift_stream` opens the upstream at `:681`. So its real window is the pool lock's wait. This corrects the reassessment's R3-1 reading, which placed the entry after the upstream open. The connect and chunk timeouts are still folded in, as constraint 2 requires, so a later reordering of `_serve_catchup` cannot silently shorten the spacing.
- **Why the factor of 2.** The windows are the code's own timeouts. A `requests` read timeout bounds each socket read, not the whole response, and a redirect adds a hop, so the factor covers one extra hop or a trickling header. A reservation slower than twice its own timeouts can be dropped. It then comes back as soon as its holder has been visible at two runs (§ Residual risks R2).
- **Why the floor.** 60 s is more than four times the live window. It matches the "on the order of 60 s" the reassessment proposed and keeps the reconciler cheap.
- **Clock.** Spacing is measured with Redis's own `TIME` (`SlotReconciler._redis_time`). A backlog of queued runs, an edited beat interval or two worker containers therefore cannot make two runs closer than `S`. A run inside `S` returns `skipped` and leaves the snapshot alone.

### Constraint 3: an unreachable relay skips the run

`SlotReconciler._run` calls `relay_client.list_channels()` after reading versions and before any write. On `RelayUnavailable`, on `RelayRefused`, on `ImproperlyConfigured`, or on a 2xx answer that is not an object carrying a `channels` list, it logs one WARNING and returns `RunResult("skipped", …)`. It writes no counter and leaves the snapshot untouched. That is the shape of `fetch_channel_stats` (`core/tasks.py:430-445`). Any other exception propagates, so a bug fails the task loudly rather than reading as zero holders. `relay_client.live_connections`'s fail-open (`relay_client.py:242-245`) is never used here. A relay that answers with an empty list, a freshly restarted one, is covered by the two-run rule under constraint 7.

### Constraints 4 and 5: a positive worker signal, a shared registry, and `worker_id` on catch-up

**The liveness key.** `vod:worker:<worker_id>` is the name the ruling recommends, kept even though catch-up uses it too. Its value is the worker id, with a TTL of `WORKER_KEY_TTL_SECONDS = 60`, refreshed every `REFRESH_INTERVAL_SECONDS = 10`. `worker_id` is `hostname-PID`: `held_records.current_worker_id()`, the formula `mwcm.py:815-824` always used, now owned by `held_records` and called from `_get_worker_id`. A restarted process gets a new PID, so its old key lapses on its own and cannot be mistaken for alive. `relay-uwsgi` runs `lazy-apps = true` (`docker/uwsgi.relay.ini:48`), so the PID is the worker's, not the master's.

**The registry** is new: `apps/proxy/vod_proxy/held_records.py`.

- `HeldRecords.hold(key, *, ttl, busy_field="") -> token` and `release(token)`.
- `holding(key, iterable, *, ttl, busy_field="")` is a generator: it holds `key` from the first item until the wrapped generator ends or is closed. `yield from` hands `close()` and exceptions through untouched, and nothing is held for a response that is never iterated.
- `held_keys()` is for tests.
- `refresh_once() -> int` never raises.
- `this_process()` returns the one per-process instance.

**The refresher.** One Lua call per iteration (`_REFRESH_SCRIPT`). It `SET`s the liveness key with its TTL. For each held record that still exists, it `EXPIRE`s the record to its own TTL and `HSET`s the record's `worker_id` to this process. If `busy_field` is set, it does this only while that field reads `'1'`, so an idle catch-up entry is never stretched back to the busy TTL. The TTLs are 3,600 s for a VOD hash (`SESSION_TTL_SECONDS`, the value `mwcm.py:341,345` hard-coded) and 600 s for a catch-up entry (`_POOL_ENTRY_TTL`, `views.py:744`). The re-stamp matters when a session another worker took over was lost with that worker: the process still streaming it claims it back within one refresh. Nothing but logging and the stats payload reads `worker_id` (`mwcm.py:716,752-755`), so the re-stamp changes no behaviour.

**Placement.** "The manager singleton" in the ruling means one refresher per process. The registry is a process singleton in `held_records.py`, and both the VOD manager and catch-up reach it through `this_process()`. It is not an attribute set in `MultiWorkerVODConnectionManager.__init__`, for two measured reasons:

- `VodRangeResponseTests` builds the manager with `__new__` and no `__init__`, so an instance attribute broke 12 of that module's tests in the prototype.
- Catch-up would otherwise have to instantiate the VOD manager to reach it.

The effect is the ruling's: exactly one refresher per `relay-uwsgi` process (`workers = 1`), off the request path.

**Start and life.** The thread starts lazily on the first `hold()`, not at import. It uses `threading.Thread(daemon=True, name="slot-holder-refresher")`, which is a greenlet under `gevent-early-monkey-patch`, the pattern `mwcm.py:861,1226` already uses. The refresher dies with its process, which is the desired failure: the key lapses and the reconciler reads the worker as gone. `SLOT_HOLDER_REFRESHER_ENABLED` is `True` in `dispatcharr/settings.py` and `False` in `dispatcharr/settings_test.py`, so tests never start a thread. They call `refresh_once()` directly, and one test pins that the first `hold()` starts exactly one thread when the flag is on.

**Wrapping** (the reassessment's constraint 5, which #513 folds into its constraint 4). `refresh_once()` catches every `Exception`. It logs one WARNING per failure streak and one INFO on recovery, and returns −1. `_run()` wraps each iteration in its own `try` as well. A test proves the loop continues past an iteration that raises.

**Hub stall.** The reconciler drops a holder only once it has been absent from two consecutive runs. A stall therefore changes a count only if it outlasts the key's TTL plus a whole run interval: about 60 + 80 = 140 s at defaults. A stall that long is a larger outage than the count.

**Where each surface holds its record.**

- **VOD.** `mwcm.py:1312-1315`: `StreamingHttpResponse(streaming_content=held_records.this_process().holding(redis_connection.connection_key, stream_generator(), ttl=SESSION_TTL_SECONDS), …)`.
- **Catch-up.** `timeshift/views.py:3643`: `_SlotReleasingStream(held_records.this_process().holding(_pool_key(pool_session_id or client_id), stream_generator(), ttl=_POOL_ENTRY_TTL, busy_field="busy"), _finish_session_backup)`. This is the same key the post-yield heartbeat refreshes (`:3116`, `:3573`). The wrap sits where the response is built, not inside `stream_generator`, which keeps it off every line #514 (D2) edits.

**`worker_id` on catch-up pool entries (constraint 5).**

- `_create_pool_session`'s mapping (`views.py:2224-2239`) gains `"worker_id": current_worker_id()`.
- `_acquire_idle_pool_session`'s re-busy `hset` (`:2170-2174`) gains it too, so an idle entry taken back into use names the process now holding it.
- An entry written before D1-2 deploys has no `worker_id`. It belongs to a process that has gone, and it counts as a record whose worker is dead.

### Constraint 6: a seeded-never-started VOD hash is bounded by `created_at`

A `vod_persistent_connection:*` hash with `active_streams <= 0` counts as a holder only while `now − created_at < W_vod` (40 s at defaults). `now` is the reconciler's Redis `TIME`; `created_at` is `relay-uwsgi`'s wall clock (`mwcm.py:192`, kept through every save by `from_dict`). On one host these agree. Across hosts, clock skew moves this bound by the skew, and the bound is belt and braces anyway: the version rule already protects a reservation that recent. A hash with `active_streams > 0` counts while its worker's key exists, however old `last_activity` is.

### Constraint 7: a record or holder counts until absent on two consecutive runs

The reconciler keeps, per counter, the set of holder identities it saw at each run: `live:<channel_id>`, `vod:<hash key>`, `catchup:<pool key>`. At run N+1 the counter may move only into this range:

```
[ |V_N ∩ V_N+1| ,  |V_N ∪ V_N+1| ]
```

The upper bound is the ruling. A holder seen at either of the last two runs keeps its slot, so it is dropped only once absent at both. That covers each kind of record the ruling names:

- **An assignment key whose relay channel vanished.** The relay crashed, or a release POST was lost.
- **A worker key missing once.** This is constraint 4's "two consecutive absences".
- **A seeded hash past its window.**

A reservation whose holder was never visible at either run moved the counter's version when it was made, and the version rule blocks the write, so it needs no record of its own. The lower bound is the same rule in the other direction: a holder earns a slot the counter lacks only once present at two consecutive runs.

The range also closes two short races that a single snapshot, or the ruling's rule applied to records alone, would lose:

- **A holder that vanishes before its release lands.** The relay deletes a channel from its map before its release POST (`manager.go:444`, then `channel.go:445`'s deferred `releaseSlot`), and a VOD session drops to `active_streams` 0 a moment before `_decrement_profile_connections`.
- **A holder that becomes visible before its reserve lands.** A reused idle VOD session increments `active_streams` at `mwcm.py:972` before it re-reserves at `:1047`, and a reconnect increments at `:1054` before reserving at `:1058`.

A relay channel in state `stopped` or `error` is not a holder, because its `run()` has returned and its release has run or is running (`channel.go:570-586`, then the deferred `releaseSlot`).

### The run, end to end

`SlotReconciler.run()` takes a non-blocking `redis_client.lock("slot_reconciler:lock", timeout=120)`. If another run holds it, this one returns `skipped`. Otherwise:

1. **Counters, from the ORM.** Every `M3UAccountProfile` with `max_streams > 0`, active or not, gives `profile_connections:<id>`. Every such profile in a server group with a fingerprint gives its credential counter, through `credential_reservation(profile)`. Unlimited profiles are excluded because a reserve never counts them.
2. **The clock.** `taken_at = TIME`. If the previous snapshot is younger than `S`, return `skipped`.
3. **Versions.** One `MGET` of every counter's version. This is read *before* any ground truth, because the next run's safety argument measures the spacing from here.
4. **The relay.** `list_channels()`, or skip the run (constraint 3).
5. **Ground truth.** Live holders from the relay's list; a 2xx answer whose `channels` is missing or not a list skips the run (Constraint 3), because it is not an empty live set. VOD and catch-up holders from one `SCAN … TYPE hash` each over `vod_persistent_connection:*` and `timeshift:pool:*`, each key followed by an `HMGET`. **Records are selected by type, never by the key's shape**: both session ids reach the key verbatim from the client (VOD's `<str:session_id>` path segment, `vod_proxy/urls.py:9-10`; catch-up's `?session_id=`, `timeshift/views.py:372,431`), so a `:` in one must not hide a live holder, and the pool's `:lock` and `:superseded` keys are strings and fall out of a hash-typed scan. Then one `MGET` of the workers' liveness keys. Holders are attributed to profiles. A profile counter's set is its own profile's holders. **A credential counter's set is the holders of every profile whose release pointer names it** (`profile_credential_release:{id}`, one `MGET`; what that profile's last reserve or switch actually counted against), **or, where a profile has no pointer, whose configuration names it today.** Attributing by today's configuration alone would lower the shared counter under streams still open when an admin makes a pooled profile unlimited, moves it out of its group, changes its login or deletes it mid-stream.
6. **Writes.** For each counter present in the previous snapshot whose version still equals the one that snapshot recorded, call `reconcile_counter(key, expected, floor, ceiling)`. The script re-checks the version at write time, atomically with the write.
7. **The snapshot.** Save `{taken_at, counters: {key: [version from step 3, sorted identities]}}` to `slot_reconciler:snapshot` as JSON, with a TTL of `max(10 × S, 600)` s. A reconciler stopped for longer starts again with a fresh baseline.

**Why a write is safe.** Suppose the version is unchanged between run N's step 3 and run N+1's write. Then every reserve, release and switch the counter reflects happened before run N's step 3. Run N+1's ground truth is read at least `S` later, which is at least twice any in-flight window. So every live reservation the counter holds is visible at N+1 (the range's upper bound keeps it), unless its holder leaked, in which case dropping it is the point.

**Logging.**

- INFO per counter moved (`"Slot reconciler moved %s from %s to %s (holders: %s at both runs, %s at either)"`), naming a credential counter by its server group only.
- INFO on a first snapshot.
- WARNING on a relay skip.
- DEBUG on nothing else.
- The task returns `{"status", "reason", "changes"}`.

**The beat entry, and where it runs.** The entry is `"reconcile-provider-slots": {"task": "core.tasks.reconcile_provider_slots", "schedule": 30.0}` in `dispatcharr/settings.py`'s `CELERY_BEAT_SCHEDULE` (`:439-459`). It goes there and not in a seeding migration because `DatabaseScheduler` re-asserts every static entry on each beat start. django-celery-beat 2.9.0's `ModelEntry.from_entry` runs `update_or_create(name=…, defaults=…)` from `setup_schedule`/`update_from_dict` (`schedulers.py:191-196,257,472`). Its defaults do not include `enabled`, so an operator who disables the row keeps it disabled. A migration would add the kind of scheduler migration whose reverse CLAUDE.md records as broken twice (`epg/migrations/0007`, `m3u/migrations/0006`). The 30 s is a tick, not the interval: a run inside `S` is skipped, so the effective interval at defaults is 90 s, the first tick past 80 s. An operator who edits the tick shorter only adds no-op runs; one who edits it longer only slows convergence.

The task itself is `core/tasks.py:reconcile_provider_slots`, next to `fetch_channel_stats` and with the same function-local import. It runs on the worker role, where beat and the default queue live, and that role already reaches the relay over the network (`apps/m3u/tasks.py:71`'s `relay_client.stop_channels`).

**Convergence at defaults, and its condition.** A leak is released two runs after its holder was last seen, 90 to 180 s at defaults, **provided the counter has one quiet run interval in that time**: no reserve, release or switch on it between two consecutive runs. An under-count is raised on the same condition. On a counter with sustained churn, one write per interval or more (a busy profile, or a shared-login counter several profiles feed), the correction waits until the churn stops, which is when the slot matters least but may be much later than 180 s. The first run after a deploy only snapshots.

**Why the version rule is not relaxed for churn.** The tempting relaxation is to write even when the version moved, if the holder set was the same at both runs. It reopens R3-1 exactly: a release plus a tune whose holder is still in flight leaves the holder set and the counter's value both unchanged while the counter now carries a different, invisible reservation, and the write would drop it. Every variant that looks at values or holder sets instead of the version has that shape, so the rule stays as #513 constraint 1 rules it and the convergence condition is stated instead of hidden.

## PR split

Three PRs, in this order. D1-2 and D1-3 depend on D1-1's script, and D1-3's reconciler depends on D1-2's worker keys and `worker_id`. Each is independently deployable: D1-1 alone lands #470 and #471; D1-2 alone writes keys nothing reads yet. Branch names: `fix/slot-script-470-471` (D1-1), `fix/slot-holder-liveness` (D1-2), `fix/slot-counter-reconciler` (D1-3), each off main after its predecessor merges.

Extract an appendix from this document with:

```bash
PLAN=docs/superpowers/plans/2026-09-26-slot-counter-reconciler.md
extract() { awk -v m="$1" '$0=="<!-- appendix-"m"-begin -->"{f=1;next} $0=="<!-- appendix-"m"-end -->"{f=0} f' "$PLAN" | sed '1d;$d'; }
extract A > /tmp/d1-1.diff && git apply --check --whitespace=error /tmp/d1-1.diff
```

The `sed '1d;$d'` strips the fence lines.

### PR D1-1: the versioned slot script (lands #470 and #471; the base of #513)

**Files** (anchors at the seed):

- `apps/m3u/connection_pool.py:198-332`. Replaced from `move_credential_slot_on_profile_switch` to the end by the script and its wrappers. `:1-196` are unchanged.
- `apps/channels/models.py:760-792`. `update_stream_profile()`'s credential move and pipeline become one `switch_profile_slot` call.
- `apps/proxy/vod_proxy/multi_worker_connection_manager.py:1556-1666`. The three uncalled methods are deleted.
- `apps/m3u/tests/slot_script_fake.py`. New: `SlotScriptFakeMixin`, the in-memory fakes' `register_script`.
- `apps/m3u/tests/test_slot_script.py`. New: 14 real-Redis tests, one of them a Hypothesis property.
- `apps/m3u/tests/test_connection_pool.py:7,23,26,621-638`. The fake gains the mixin, and `_safe_decr`'s import and test are retargeted (§ Tests).
- `apps/m3u/tests/test_property_connection_pool.py:27-29,50,95-103`. The same.
- `apps/proxy/tests/test_next_source_api.py:16,21`, `apps/proxy/tests/test_next_source_resolution.py:15,19`, `apps/proxy/vod_proxy/tests/test_profile_connections.py:10,13`. Each fake gains the mixin; nothing else changes.
- `dispatcharr/test_discovery.py:49-54`. Two `_PATH_ALIASES` entries: `apps/m3u/connection_pool` routes to m3u, channels, proxy, vod_proxy and timeshift; `apps/m3u/tests/slot_script_fake` to m3u, proxy and vod_proxy.
- `tests/test_ci_test_routing.py:76`. One routing test is added.
- `CLAUDE.md:131`. One Known-defects bullet goes before `#190 is closed by deletion`: the rule that every counter write goes through the script.

**Tasks.**

1. **Pre-flight.** Confirm the seed anchors: `git show "${SEED}:apps/m3u/connection_pool.py" | sed -n '198p;232p;289p;325p'` prints the four `def` lines, and `git show "${SEED}:apps/channels/models.py" | sed -n '787,792p'` prints the pipeline. If main has moved these, stop and report; do not re-derive.
2. **Apply Appendix A.** `git apply --whitespace=error`.
3. **The writer grep.** Run the third grep from Constraint 1 against the working tree. It must print nothing, with exit 1 under `pipefail`.
4. **Labels.** `python3 scripts/ci_backend_test_labels.py` on the changed paths selects all fifteen labels (`dispatcharr/` is a shared prefix). Run them on fresh databases. Expect the "+ D1-1" column above.
5. **Break-checks** (each applied alone, then reverted):
   - **Restore the seed's Python reserve and release.** Append `git show "${SEED}:apps/m3u/connection_pool.py"`'s lines from `def _safe_decr` to the end of the file, so the seed's definitions win. Eight tests fail, and the three parity tests error with `AttributeError: '_DictRedis' object has no attribute 'incr'` because the seed's code calls `incr`, which the minimal fake lacks (a side effect of the edit, not the mechanism). The eight include:
     - `test_470_reserve_side_race_admits_one_stream_from_minus_one_with_a_cap_of_one`: `AssertionError: 2 != 1 : 2 streams admitted against a cap of one (#470)`
     - `test_470_release_side_race_leaves_the_counter_equal_to_the_streams_held`: `AssertionError: 0 != 2 : a release lost two live streams from the count (#470)`
     - `test_a_negative_profile_counter_does_not_lift_max_streams`: `Lists differ: [True, True, True] != [True, False, False]` … `a negative profile counter lifted the cap (#471)`
     - `test_a_release_repairs_a_negative_profile_counter`: `-2 != 0`
     - `test_each_write_bumps_the_version_of_the_counter_it_writes`: `(0, 0) != (1, 1)`
     - `test_a_refused_reserve_writes_nothing_and_bumps_nothing`: `a refused reserve wrote a counter or moved a version` (the seed's INCR-then-DECR leaves a `0` where the script leaves no key)
     - `test_a_switch_bumps_both_profile_versions_in_one_step`: `(1, 1) != (2, 1)`; `test_a_moved_version_blocks_the_write`: `(1, 1, 0) != (-1, 1, 1)`
   - **Drift the fake.** In `slot_script_fake.py`'s `_give_back`, delete the `elif current < 0` branch. `SlotScriptFakeParityTests.test_reserve_release_refusal_and_repair_sequences_agree` fails with `'-4' != '0' : profile_connections:<id>`.
   - **Drift the fake's `credential_full` branch to write the profile counter before refusing** (the seed's shape; the reviewer's probe that the fixed sequences missed). `SlotScriptFakeParityProperties.test_the_fake_matches_the_lua_after_every_step` errors with Hypothesis's grouped failure, whose members read `'1' != None : step 0 ('reserve', 'a'): profile_connections:<id> differs between the fake and the Lua`.
   - **Delete the production Lua's negative repair** (`elseif c < 0 then write(k, 0)` in `give_back`). The property fails with `'0' != '-1' : step 0 ('release', 'a'): profile_connections:<id> differs between the fake and the Lua`, as do `test_reserve_release_refusal_and_repair_sequences_agree` and `test_a_release_repairs_a_negative_profile_counter`. The fake-backed `test_property_connection_pool.py` and `test_connection_pool.py` stay green under this edit, because they run the fake: see § Existing tests changed.
   - **Drop the alias.** Delete the new `apps/m3u/connection_pool` alias. `test_slot_script_change_runs_every_label_that_reserves_a_slot` fails with `Items in the second set but not the first: 'apps.proxy.vod_proxy.tests' 'apps.timeshift.tests' 'apps.channels.tests'`.
6. **Lint.** Run `python3 scripts/check_credential_logging.py` on every touched `.py`. It exits 0.

**Tests added** (all in `apps.m3u.tests`, real Redis):

| Class | Tests | What they pin |
|---|---|---|
| `SlotScriptVersionTests` | `test_each_write_bumps_the_version_of_the_counter_it_writes`, `test_a_refused_reserve_writes_nothing_and_bumps_nothing`, `test_a_switch_bumps_both_profile_versions_in_one_step`, `test_a_switch_refused_by_the_new_login_writes_nothing` | constraint 1: every writer bumps, nothing else does |
| `SlotScriptRepairTests` | `test_a_negative_profile_counter_does_not_lift_max_streams`, `test_a_release_repairs_a_negative_profile_counter` (#471); `test_470_reserve_side_race_…`, `test_470_release_side_race_…` (#470's two interleavings, forced deterministically) | atomic repair. The interleavings wrap the real client and pause the first thread after its `incr`/`get` on the credential key until the second finishes. Under the seed's Python that is the race; under the script no such call exists and the two serialise. |
| `ReconcileOpTests` | `test_a_moved_version_blocks_the_write` (1→0→1), `test_an_unmoved_version_clamps_and_does_not_bump`, `test_an_absent_counter_clamped_to_zero_is_not_created` | the `reconcile` op D1-3 writes through |
| `SlotScriptFakeParityTests` | `test_reserve_release_refusal_and_repair_sequences_agree`, `test_switch_and_reconcile_sequences_agree` | the Python fake answers exactly as the Lua for two fixed sequences: same returns, same final value for every key |
| `SlotScriptFakeParityProperties` | `test_the_fake_matches_the_lua_after_every_step` (Hypothesis, the shared `dispatcharr-ci` profile: 200 derandomized examples) | random reserve/release/switch sequences of up to 15 steps over five profiles, three of which share one login (so `credential_full` is reached on reserve and on switch) plus an unlimited and an ungrouped one, from drifted starting counters (absent, −3…3); the return and every key are compared after every step |

`tests.test_ci_test_routing.ChangedPathRoutingTests.test_slot_script_change_runs_every_label_that_reserves_a_slot` is also added.

**PR description draft:**

> **fix(m3u): every provider-slot counter write goes through one versioned Lua script**
>
> `profile_connections:{id}` and `server_group_connections:{group}:{fp}` were written from four places: `connection_pool.py`'s Python reserve and release, `Channel.update_stream_profile()`'s own DECR/SET/INCR pipeline, and three VOD manager methods with no caller. Both negative-counter repairs were a GET then a SET. This PR puts every write inside one Lua script (`connection_pool._SLOT_SCRIPT`: reserve, release, switch and a version-guarded clamp for the reconciler that follows). Every write bumps `slot_version:<counter>`. The script checks both caps before writing either, so a refused reserve writes nothing.
>
> - #470 (planned in PR D1-1): both interleavings from the issue are forced deterministically against real Redis; they admit two streams against a cap of one, and lose two live streams from the count, under the old code, and neither happens now.
> - #471 (planned in PR D1-1): a negative profile counter no longer lifts `max_streams`, and a release repairs it.
> - #513 (planned in PR D1-3): this is its constraint 1, the version every writer bumps.
>
> Deleted: `MultiWorkerVODConnectionManager.create_connection`, `remove_connection` and `update_connection_activity`, which had no caller and were the only writers of `vod_proxy:connection:*`.
>
> Tests changed (the in-memory fakes cannot run Lua): five fakes gain `SlotScriptFakeMixin`, whose Python answer is held to the Lua by `SlotScriptFakeParityTests` on a live Redis. The two tests that called the deleted `_safe_decr` now call `release_profile_slot`, with the same inputs and the same expected values. Before and after are in the plan, `docs/superpowers/plans/2026-09-26-slot-counter-reconciler.md` § Tests.
>
> Measured: all fifteen labels green on fresh databases (m3u 245 → 259, tests 168 → 169). Reserve is 3 round trips → 1 and release 6 → 1; the loopback median for the pair is 454 µs → 122 µs. The tune-path query ledger is unchanged.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

In the implementation PR, each "(planned in PR D1-1)" line becomes that issue's closing keyword, and #513's line stays a reference.

### PR D1-2: worker liveness, the held-record registry, and `worker_id` on catch-up (part of #513)

**Files:**

- `apps/proxy/vod_proxy/held_records.py`. New, 203 lines: the registry, the refresher and its Lua. `held_entries()` exposes each held `(key, ttl, busy_field)` for the tests.
- `dispatcharr/test_discovery.py`. A third `_PATH_ALIASES` entry: `apps/proxy/vod_proxy/held_records` routes to `apps.proxy.vod_proxy`, `apps.proxy` and `apps.timeshift`, whose tests hold or read its records.
- `tests/test_ci_test_routing.py`. `test_held_records_change_runs_every_label_that_holds_or_reads_a_record` is added.
- `apps/proxy/vod_proxy/multi_worker_connection_manager.py`:
  - `:16` imports `held_records`.
  - `:95` adds `SESSION_TTL_SECONDS = 3600`, and `:341,345` use it.
  - `:815-824`: `_get_worker_id` delegates to `held_records.current_worker_id()`.
  - `:1312-1315` wraps `stream_generator()` in `holding(…)`.
- `apps/timeshift/views.py`:
  - `:41` imports `held_records` and `current_worker_id`.
  - `:2170-2174` and `:2236-2239` add `worker_id` to the pool entry.
  - `:3643` wraps `stream_generator()` in `holding(…)`.
- `dispatcharr/settings.py:438` adds `SLOT_HOLDER_REFRESHER_ENABLED = True`; `dispatcharr/settings_test.py:33` sets it `False`.
- `apps/proxy/vod_proxy/tests/test_held_records.py`. New: 12 tests.
- `apps/timeshift/tests/test_pool_worker_id.py`. New: 3 tests. It imports `StreamFromProviderStatusMappingTests` inside the test, because a `TestCase` class imported at module level is collected and run a second time (measured: 38 tests instead of 15).

**Tasks.**

1. Apply Appendix B on top of D1-1.
2. Run the labels (all fifteen, since `dispatcharr/` is touched). Expect the "+ D1-2" column.
3. **Break-checks:**
   - **Drop the VOD wrap** (`streaming_content=stream_generator()`). `VodStreamHoldsItsSessionTests.test_the_session_is_held_from_the_first_chunk_until_the_stream_ends`: `'vod_persistent_connection:vod_1_1' not found in [] : a streaming VOD response did not hold its session`.
   - **Drop the catch-up wrap.** `CatchupStreamHoldsItsPoolEntryTests.test_the_pool_entry_is_held_from_the_first_chunk_until_close`: `'timeshift:pool:pool-s1' not found in [] : a streaming catch-up response did not hold its pool entry`.
   - **Replace the refresh script's busy guard with `if true then`.** `test_a_catch_up_entry_is_refreshed_only_while_busy`: `1 != 0 : an idle catch-up entry was refreshed to the busy TTL`.
   - **Delete the refresh script's `HSET … worker_id`.** `test_a_held_vod_session_outlives_its_own_ttl_while_held`: `'someone-else' != 'test-host-…'`.
   - **Drop `worker_id` from `_create_pool_session`'s mapping.** `test_a_created_entry_records_this_process`: `None != '<host>-<pid>'`.
   - **Drop it from `_acquire_idle_pool_session`.** `test_an_idle_entry_taken_back_records_the_process_taking_it`: `'host-that-died-1' != '<host>-<pid>'`.
   - **Remove `_run`'s own `try`/`except`.** `test_the_loop_keeps_going_after_an_iteration_raises` errors with `RuntimeError: an iteration blew up`: the exception escaped the loop.
   - **Drop `busy_field="busy"` from the catch-up wrap.** `test_the_pool_entry_is_held_from_the_first_chunk_until_close`: `('timeshift:pool:pool-s1', 600, 'busy') not found in [('timeshift:pool:pool-s1', 600, '')] : a streaming catch-up response held its pool entry without the busy guard or the busy TTL`.
   - **Give the VOD wrap the catch-up TTL (`ttl=600`).** `test_the_session_is_held_from_the_first_chunk_until_the_stream_ends`: `('vod_persistent_connection:vod_1_1', 3600, '') not found in [('vod_persistent_connection:vod_1_1', 600, '')] : a streaming VOD response held its session with the wrong TTL or a busy guard`.
   - **Drop the `held_records` alias.** `test_held_records_change_runs_every_label_that_holds_or_reads_a_record` fails with `Items in the second set but not the first:`.
4. `test_vod_lock_contention.py` passes unchanged. That is Global constraint 3's pin.

**Tests added:**

| Module | Tests | What they pin |
|---|---|---|
| `test_held_records.py` (real Redis) | `test_refresh_sets_the_worker_liveness_key_with_a_short_ttl`, `test_a_held_vod_session_outlives_its_own_ttl_while_held`, `test_a_catch_up_entry_is_refreshed_only_while_busy`, `test_a_record_already_gone_is_not_recreated`, `test_holding_registers_from_the_first_item_until_the_end_or_close` | the positive signal and the re-EXPIRE (constraint 4) |
| same (no Redis) | `test_refresh_once_swallows_a_redis_failure_and_logs_once`, `test_the_loop_keeps_going_after_an_iteration_raises`, `test_the_first_hold_starts_one_refresher_thread`, `test_no_refresher_thread_in_tests`, `test_this_process_is_one_registry_shared_by_every_caller`, `test_the_vod_manager_and_catch_up_record_the_same_worker_id` | wrapping, start-once, one registry per process |
| same | `VodStreamHoldsItsSessionTests.test_the_session_is_held_from_the_first_chunk_until_the_stream_ends` | the VOD wrap, driven through `stream_content_with_session` with `VodRangeResponseTests`' harness, including the registered `(key, 3600, "")` |
| `test_pool_worker_id.py` | `test_a_created_entry_records_this_process`, `test_an_idle_entry_taken_back_records_the_process_taking_it`, `test_the_pool_entry_is_held_from_the_first_chunk_until_close` | constraint 5, including the catch-up wrap's registered `(key, 600, "busy")` |
| `tests/test_ci_test_routing.py` | `test_held_records_change_runs_every_label_that_holds_or_reads_a_record` | the routing alias |

**PR description draft:**

> **feat(proxy): a liveness key per relay-uwsgi process, and the records its streams hold**
>
> The provider-slot reconciler (#513, planned in PR D1-3) must count a VOD session or catch-up pool entry only while the process holding it is alive. Recency is the wrong signal: a paused player's generator sits at a `yield` and nothing refreshes `last_activity`, while the provider connection stays open.
>
> This adds `apps/proxy/vod_proxy/held_records.py`. Each process runs one refresher (a greenlet under gevent, off the request path), which every 10 s sets `vod:worker:<hostname-PID>` (TTL 60 s) and re-EXPIREs, and re-stamps with its own `worker_id`, every record its streaming responses currently hold. VOD and catch-up responses hold their record from the first chunk until the stream ends or closes. Catch-up pool entries now carry `worker_id`. The refresher catches its own exceptions, so it cannot die silently, and it dies with its process, which is what lets the key lapse. Tests never start it (`SLOT_HOLDER_REFRESHER_ENABLED = False` in `settings_test.py`).
>
> Nothing reads the new keys until D1-3. `test_vod_lock_contention.py` is untouched and green: the refresher writes only `EXPIRE` and `worker_id`, never `active_streams`.
>
> Measured: all fifteen labels green on fresh databases (vod_proxy 92 → 104, timeshift 451 → 454, tests 169 → 170).
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR D1-3: the reconciler, its beat entry, and the ADR 0005 note (lands #513)

**Files:**

- `apps/proxy/slot_reconciler.py`. New, 404 lines.
- `apps/proxy/tests/test_slot_reconciler.py`. New, 503 lines: 21 tests, real Redis plus the test database.
- `core/tests/test_reconcile_provider_slots.py`. New, 20 lines: the beat-entry test, in `core.tests` because it pins `dispatcharr/settings.py` and `core/tasks.py`, whose edits select that label.
- `apps/proxy/vod_proxy/multi_worker_connection_manager.py`. After `SESSION_TTL_SECONDS` it adds `UPSTREAM_TIMEOUT = (10, 10)` and `UPSTREAM_ATTEMPTS = 2`; `:499,518` use `UPSTREAM_TIMEOUT`.
- `apps/timeshift/views.py:2133-2137`. `POOL_LOCK_WAIT_SECONDS = 5`, defined immediately above `_pool_lock` and used as its `blocking_timeout`. It is deliberately not beside `_POOL_WAIT_SECONDS` at `:747`, because D2's PR #517 inserts lines at `:743-746` and a hunk there would stop applying.
- `core/tasks.py:461`. `reconcile_provider_slots`, inserted before `rehash_streams`.
- `dispatcharr/settings.py:458`. The beat entry, appended after `check-account-expirations` (`:454-458`).
- `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md:176`. One dated consequence bullet.
- `CLAUDE.md`. D1-1's bullet gains its reconciler sentence.

**Tasks.**

1. Apply Appendix C on top of D1-2.
2. Run the labels (all fifteen). Expect the "+ D1-3" column.
3. Run the break-checks in § Tests below, each alone.
4. **Deploy note for the PR body.** The first run after deploy only snapshots. A leak is released two runs after its holder was last seen (90 to 180 s at defaults) once its counter has had one quiet run interval; on a counter with continuous churn it waits for the churn to stop.

**PR description draft:**

> **feat(proxy): recompute the provider-slot counters from ground truth**
>
> #513 (planned in PR D1-3). The provider-slot counters had no TTL, no owner lease and no reconciliation. A relay-go crash, a release POST lost while `api-uwsgi` restarted (any deploy), a relay-uwsgi crash under VOD and an abandoned catch-up session each leaked a slot for good. A Redis restart or a non-atomic repair wrote one down under a live holder.
>
> A beat task on the worker role (`core.tasks.reconcile_provider_slots`, a 30 s tick) now recomputes each counter from:
>
> - the relay's channel list;
> - VOD sessions with `active_streams > 0` whose worker is alive (#513's liveness key, from D1-2), plus a seeded session inside the VOD connect window;
> - busy catch-up pool entries whose worker is alive.
>
> It writes only when the counter's version (from D1-1) has not moved since its previous run, checked atomically with the write. It never lowers a counter below the holders seen at either of its last two runs, or raises it above those seen at both. Runs are spaced at twice the longest in-flight window, 80 s at defaults, read at run time from the relay's tune budget, the VOD upstream timeout and the operator's catch-up timeouts. A run that cannot reach the relay does nothing.
>
> Records are selected by Redis type, never by key shape, because both session ids are client-chosen and may contain `:`. A shared-login counter's holders are attributed through each profile's release pointer, so an admin editing or deleting a pooled profile mid-stream does not lower it under streams still open. A relay answer with no channel list skips the run. Convergence needs one quiet run interval on the counter; under sustained churn the correction waits (the version rule is #513's constraint 1 and relaxing it reopens the release-then-tune race).
>
> Tests: the eleven interleavings #513 names and five from the plan's review (colon session ids on both surfaces, attribution through an edit and a delete, an unusable relay answer), each against real Redis with a named break-check, plus the spacing and the beat entry. ADR 0005 gains a consequence note.
>
> Measured: all fifteen labels green on fresh databases (proxy 399 → 420, core 138 → 139).
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Tests

### The eleven tests #513 names, and five from review round 1

These live in `apps/proxy/tests/test_slot_reconciler.py`, in the `apps.proxy.tests` label. Every label's CI job starts a real Redis (`scripts/ci_bootstrap_backend.sh:65-71`). At the seed the one label with live-Redis tests is `apps.proxy.vod_proxy.tests` (`TestVodActiveStreamsRealRedis`); D1-1 adds `apps.m3u.tests`. The reconciler's tests sit with the module they test, and Global constraint 8's fail-under-CI rule keeps them from going hollow where Redis is missing.

Each test drives `SlotReconciler(redis, clock=…, list_channels=…)`. The fake clock is advanced past `run_spacing_seconds()` between runs, and the relay's answer is set per step. Every break-check below was run, and each message is quoted from the run.

| # | Test | Mechanism pinned | Wrong edit that reddens it → message |
|---|---|---|---|
| 1 | `OrphanTests.test_an_orphan_is_dropped_after_two_absent_runs` | constraint 7: a holder keeps its slot through one absent run and loses it at the second | ceiling `len(now_ids)` instead of `len(then_ids \| now_ids)` → `0 != 1 : an orphan was dropped after one absent run` |
| 2 | `InFlightTests.test_an_in_flight_live_reservation_is_not_released` | constraint 1: a reserve since the last run blocks the write | "ignore the version": delete the Python `if versions.get(key) != expected: continue` **and** pass `versions.get(key, 0)` to `reconcile_counter`. The two guards are redundant by design, so both must go. → `1 != 2 : an in-flight live reservation was released` |
| 3 | `…test_an_in_flight_vod_reservation_is_not_released` | the same, VOD (reserved before the hash exists) | same edit → `1 != 2 : an in-flight VOD reservation was released` |
| 4 | `…test_an_in_flight_catch_up_reservation_is_not_released` | the same, catch-up (reserved, pool lock not yet taken) | same edit → `1 != 2 : an in-flight catch-up reservation was released` |
| 5 | `ReleaseThenTuneTests.test_a_release_then_a_tune_between_runs_is_not_clobbered` | R3-1: the counter reads 1 at both runs but counts a different reservation; the value is stable and the version is not | "compare values, not versions": snapshot the counter's value instead of its version, compare it, and pass the fresh version → `0 != 1 : a release then a tune between runs lost the tune's slot`. This is the only test that edit reddens, which is the point of it. |
| 6 | `FailoverTests.test_a_profile_changing_failover_between_runs_is_not_clobbered` | R4-1: `update_stream_profile()` bumps the new profile's version | restore the seed's DECR/SET/INCR pipeline in `update_stream_profile()` → `0 != 1 : a failover's reservation on the new profile was dropped` |
| 7 | `RefusedReserveTests.test_a_refused_reserve_does_not_trigger_a_write`, with `…_does_not_block_a_due_correction` | a refusal writes nothing, so it neither makes the reconciler write nor holds back a due correction | make the script's `profile_full` branch write `pc + 1` then `pc`, as the seed did → `a refused reserve moved the counter's version` and `2 != 1 : a refused reserve blocked the leak's correction` |
| 8 | `RelayUnreachableTests.test_an_unreachable_relay_leaves_every_counter_untouched` | constraint 3, one subtest each for `RelayUnavailable`, `RelayRefused` and `ImproperlyConfigured`: status `skipped`, counter and snapshot byte-identical | fail open (treat the three as `{"channels": []}`) → `'reconciled' != 'skipped' : an unreachable relay did not skip the run`, in all three subtests |
| 9 | `WorkerLivenessTests.test_a_paused_viewer_is_counted_while_its_worker_lives_and_dropped_two_runs_after_it_dies` | constraint 4, both halves: a VOD hash and a busy pool entry, two hours stale, still count while their worker key lives; after it lapses they count one more run, then drop | "recency": count a VOD hash while `now − last_activity < 600` → `(0, 1) != (1, 1) : a paused viewer with a live worker lost its slot`; and test 1's edit → `(0, 0) != (1, 1) : a dead worker's records dropped after one run` |
| 10 | `SeededHashTests.test_a_seeded_never_started_hash_is_not_counted_past_its_window`, with `…_inside_its_window_is_counted` | constraint 6 | drop the `created_at` bound → `1 != 0 : a seeded hash was counted past the VOD window` |
| 11 | `ConcurrentIncrTests.test_a_concurrent_incr_is_not_clobbered` | the version check happens inside the script, atomically with the write: a reserve landing between the reconciler's reads and its write wins | delete `if v ~= tonumber(ARGV[2]) then return {-1, c, c} end` from the script's `reconcile` op → `0 != 2 : a concurrent INCR was clobbered` |
| 12 | `ColonSessionIdTests.test_a_vod_holder_with_a_colon_in_its_session_id_keeps_its_slot` | review finding 1: a client-chosen VOD session id containing `:` (`vod_proxy/urls.py:9-10`'s `<str:session_id>`) does not hide a live holder | select records by colon count again (`if key.count(":") != pattern.count(":"): continue`) → `0 != 1 : a live VOD holder with ':' in its session id lost its slot` |
| 13 | `ColonSessionIdTests.test_a_catch_up_holder_with_a_colon_in_its_session_id_keeps_its_slot` | the same for catch-up's `?session_id=`, with a `:lock` and a `:superseded` string beside it that must neither count nor break the scan | the colon-count edit → `0 != 1 : a live catch-up holder with ':' in its session id lost its slot`; and a scan without `_type="hash"` → `redis.exceptions.ResponseError: WRONGTYPE Operation against a key holding the wrong kind of value` (ERROR) |
| 14 | `CredentialAttributionTests.test_making_a_pooled_profile_unlimited_mid_stream_keeps_its_holders_counted` | review finding 3: holders count against the credential counter their profile's release pointer names | attribute by today's configuration only (`key = config_credential.get(profile_id)`) → `1 != 2 : the shared-login counter dropped under two live streams` |
| 15 | `CredentialAttributionTests.test_deleting_a_pooled_profile_mid_stream_keeps_its_holders_counted` | the same for a profile deleted mid-stream | the same edit → the same message |
| 16 | `RelayAnswerTests.test_a_relay_answer_without_a_channel_list_skips_the_run` | review nit 8: a 2xx body with `channels` missing, `None`, a string, or a non-object body is not an empty live set | read a missing list as `[]` → `'reconciled' != 'skipped' : a relay answer with no channel list was read as an empty live set`, in each of the four subtests |

**Also in the module.**

- `SpacingTests.test_the_spacing_follows_the_widest_window_including_operator_settings` asserts the windows from the imported constants (`control_plane.ATTEMPTS`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `RETRY_DELAY`; `UPSTREAM_ATTEMPTS`, `UPSTREAM_TIMEOUT`; `POOL_LOCK_WAIT_SECONDS`), so a legitimate edit to one of them moves the expectation with it; a patched `connection_timeout` of 60 moves the spacing to 190 s. `test_the_default_spacing_is_80_seconds` is the one literal pin. A fixed 60 s spacing reddens both with `60.0 != 80.0`.
- `test_a_run_inside_the_spacing_writes_nothing`.
- `core.tests.test_reconcile_provider_slots.ReconcileProviderSlotsBeatEntryTests.test_the_beat_entry_names_the_task_on_a_tick_shorter_than_the_spacing_floor`, moved to `core.tests` because an edit to `dispatcharr/settings.py` or `core/tasks.py` selects that label.

### Existing tests changed

Each change listed here is either the thing being changed, or a fake gaining the ability to run the script the code under test now calls. No assertion is removed or loosened.

**What these tests now exercise.** After D1-1 every counter test that runs on an in-memory fake (the five Hypothesis properties in `test_property_connection_pool.py`, the reserve/release tests in `test_connection_pool.py`, the two retargeted tests below, and the proxy and VOD tests whose fakes gain the mixin) executes `slot_script_fake.py`'s Python, **not the production Lua**. They still pin the callers' behaviour against a faithful script, but deleting a repair from the production Lua leaves them green (measured). The production Lua is pinned by `apps/m3u/tests/test_slot_script.py` on a live Redis: its version, repair, race and reconcile tests, and `SlotScriptFakeParityProperties`, which ties the fake to the Lua over random sequences so the fake-backed tests cannot drift from what they stand in for.

| Test file | Before (seed) | After | Why |
|---|---|---|---|
| `apps/m3u/tests/test_connection_pool.py:26` | `class FakeRedis:` | `class FakeRedis(SlotScriptFakeMixin):`, plus the import | the code now calls `register_script`; the mixin answers it in Python, held to the Lua by the parity tests |
| `…:7` | imports `_safe_decr` | import removed | `_safe_decr` is folded into the script's `give_back` |
| `…:621-638` `CredentialCounterRepairTests.test_safe_decr_repairs_a_counter_already_below_zero` | `_safe_decr(redis, "negative_one")` → 0; `_safe_decr(redis, "negative_three")` → 0 | `test_release_repairs_a_credential_counter_already_below_zero`: sets `profile_credential_release_key(1)` to `"negative_one"`, calls `release_profile_slot(1, redis)`, expects 0; the same for −3 through profile 2 | same inputs, same expected values, through the public entry point, which now runs the fake's copy of the repair; the Lua's copy is pinned by `test_a_release_repairs_a_negative_profile_counter` and the parity property. Docstring updated to say so. |
| `apps/m3u/tests/test_property_connection_pool.py:50` | `class FakeRedis:` | `class FakeRedis(SlotScriptFakeMixin):`, plus the import | as above |
| `…:29` | imports `_safe_decr` | removed | as above |
| `…:95-103` `SafeDecrProperties.test_safe_decr_lands_on_one_less_but_never_below_zero` | `FakeRedis({"k": start})`; `_safe_decr(redis, "k")`; expects `max((start or 0) - 1, 0)` | `test_a_release_lands_one_less_but_never_below_zero`: `FakeRedis({profile_connections_key(1): start})`; `release_profile_slot(1, redis)`; same expectation, same `@given` and both `@example`s | as above, and likewise now exercising the fake. With no credential pointer, a release gives back exactly the profile counter. |
| `apps/proxy/tests/test_next_source_api.py:21` | `class FakeRelayApiRedis:` | `(SlotScriptFakeMixin)`, plus the import | the fake runs the script; no assertion changes |
| `apps/proxy/tests/test_next_source_resolution.py:19` | `class FakeControlPlaneRedis:` | `(SlotScriptFakeMixin)`, plus the import | the same |
| `apps/proxy/vod_proxy/tests/test_profile_connections.py:13` | `class FakeRedis:` | `(SlotScriptFakeMixin)`, plus the import | the same |

Measured before the fakes were changed, D1-1's code alone fails 2 modules in `apps.m3u.tests` on the `_safe_decr` import, 21 tests in `apps.proxy.tests` and 2 in `apps.proxy.vod_proxy.tests`. All of them pass once the five fakes gain the mixin and the two tests are retargeted, with no assertion edited. `apps.channels.tests` and `apps.timeshift.tests` needed no change, because their tests patch `reserve_profile_slot`/`release_profile_slot` or never reach them.

`test_property_connection_pool.py`'s module docstring still cites `_safe_decr` at `:232`. It is anchored "at seed a54b09a9", so it stays, as a record of the seed it was written against.

## Overlap

| Item | State at planning | Files shared with D1 | Resolution |
|---|---|---|---|
| **#514 (D2), PR #517** | merged as `02a5fe5c` | `apps/timeshift/views.py` (D2's hunks at seed `:743-746`, `:2314-2344`, `:2557`, `:3528-3561`); `apps/timeshift/tests/test_views.py` (D2 appends tests at `:4554`) | D1-2's hunks are at `:41`, `:2170-2174`, `:2236-2239` and `:3640-3646`; D1-3's at `:2133-2137`. The nearest is D1-2's `:3643` wrap, 80 lines after D2's last hunk. D1-3's constant was moved beside `_pool_lock` so as not to sit three lines from D2's `:743` insertion. **Verified:** all three appendices apply on `02a5fe5c`, and m3u, proxy, vod_proxy and timeshift (458) are green there with them applied. `test_pool_worker_id.py` imports only `_FakeRedis`, `_fake_upstream` and `_seed_pool_session` from `test_views.py` (and one fixture class, function-locally), none of which D2 touches. |
| **#470** | open, `needs-triage` | `connection_pool.py` | fixed by D1-1 |
| **#471** | open, `needs-triage` | `connection_pool.py` | fixed by D1-1 |
| **#356** (shared credential release key) | open, no plan | `connection_pool.py`'s pointer semantics | not fixed here. D1 bounds its symptom: the credential slot a second release fails to return is dropped two runs after that stream ends. #356's own fix (a per-stream token or a count under the pointer) must be made **inside `_SLOT_SCRIPT`'s `reserve`, `release` and `switch` ops**, keep bumping versions, and update `slot_script_fake.py` and its parity tests in the same PR. |
| **ADR 0007 PR, #516** | merged at `1b3097e8` | `CLAUDE.md` (its hunks at `:4`, `:79`, `:101`, `:160`), `CONTEXT.md`, ADR 0007 | no shared hunk. D1-1's and D1-3's `CLAUDE.md` hunks sit at `:128-131`, and D1-3 edits ADR 0005, not 0007. Verified: all three appendices apply on `1b3097e8`. D1-3's ADR 0005 note cites ADR 0007. ADR 0007's own consequence "the counter drift is an open defect, tracked by #513" is time-conditioned ("until it lands") and is left as written. |
| **Metrics ledger** | — | — | none of #470, #471, #356 or #513 is in `metrics/curated/defects.yml`, so no metrics change |

## What this plan does not do

- **#356's cause.** The per-profile credential release pointer is unchanged; see Overlap.
- **The Go-side release retry.** A bounded retry in `relay/httpapi/events.go:56-57`'s `ReleaseVia` would close only the lost-POST path, and only while the relay process survives. D1 does not need it. It would shorten convergence for that one path, so it could be a follow-up of its own.
- **B2, Redis DB separation.** Every key D1 adds (`slot_version:*`, `vod:worker:*`, `slot_reconciler:*`) lives in DB 0 beside the keys it describes.
- **Deleting orphan assignment keys.** `channel_stream:*` and `stream_profile:*` are never deleted by the reconciler. The reassessment's first draft did that, and its round 1 showed the race. The residual this leaves is R1 below.
- **Unlimited profiles, deleted profiles and stale credential keys.** Their counters are not reconciled, because no admission check reads any of them. `update_stream_profile()`'s `take` on an unlimited new profile keeps the seed's INCR, and changing that would be a behaviour change #513 does not ask for.
- **The VOD manager's dead code outside the counter.** `cleanup_stale_persistent_connections` and `cleanup_persistent_connection` stay: they are uncalled but write no counter directly. So do the now-unread `connection_ttl` and `session_ttl` attributes (`mwcm.py:810-811`).
- **The unscheduled `fetch_channel_stats`.** It is reached only through `beat_periodic_task` (`core/tasks.py:50`), which nothing schedules. That is the reassessment's aside, and it is not taken up.
- **Metrics or structured logs.** Observability is the INFO lines and the task's return value.

## Residual risks

- **R1: reuse after a drop.** Once the reconciler drops an orphan's slot, the orphan's `stream_profile` key is still there. A later tune of that same channel takes `_stream_assignment_is_reusable`'s `present=False` branch (`models.py:496-497`) and reuses the assignment without an `INCR`. That channel then runs uncounted until it has been visible at two runs with a quiet interval between (about 90 to 180 s on a quiet counter, longer under churn; see Convergence), so the cap is lifted by one for that long. It needs a prior leak plus a re-tune of the same channel. At the seed, the same path reused the leaked reservation, which was right for that channel but left a permanent over-count. A follow-up could make that branch reserve; it is not in #513's scope.
- **R2: a reservation slower than twice its window.** A holder still invisible a full `S` after its reserve can be dropped, then raised again once it has been visible at two runs.
- **R3: clock skew across hosts.** It moves constraint 6's `created_at` bound by the skew; see Constraint 6.
- **R4: a hub stall longer than about 140 s.** It drops a live worker's records until it recovers plus two runs.
- **R6: sustained churn delays convergence.** See Convergence: a counter written between every pair of runs is never corrected until the writes stop. The version rule is constraint 1's ruling and relaxing it reopens R3-1, so this is a stated bound rather than a fix.
- **R7: a stale release pointer.** A profile's pointer survives only when the stream that set it leaked its release. If that profile is later made unlimited and streams again, its new holders reserved nothing on the shared login but are attributed to it through the stale pointer until they end. That is an over-count (the cap tightened), the safe direction, bounded by those streams' lifetime.
- **R5: a degraded failover.** The relay moves to an unreserved alternate when Django is unreachable. The reconciler then attributes the channel to the alternate's profile, which is correct for the provider. The eventual release, which carries the original assignment, gives back the old profile's slot: an under-count of one on the old profile, corrected two runs later.

<!-- The three appendices below are `git diff` output between scratch commits built on the seed, spliced verbatim. Verified per § What was measured. -->

## Appendix A: PR D1-1, against the seed `b2d0ff5e2e`

Produced by `git diff b2d0ff5e2e 63c1871d` in the scratch clone (13 files, 1,389 lines of diff).

<!-- appendix-A-begin -->
```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 9a9a17ff..69e27db9 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -128,6 +128,7 @@ Correctness:
 - **A buffering timeout with no alternate no longer asks `next-source` on every progress record** ([#302](https://github.com/D10Scot/Dispatcharr/issues/302), fixed in #394): a failed switch defers the next ask by one `buffering_timeout`.
 - **An fMP4 viewer is no longer dropped 40s into a stall a TS viewer survives** ([#222](https://github.com/D10Scot/Dispatcharr/issues/222), fixed in #400, row 12): `serveFMP4Client` now leaves by the TS loop's exit, never on a healthy channel and after `MAX_KEEPALIVE_DURATION` on an unhealthy one, with no keepalive bytes written.
 - **`channel_stream:*`/`stream_profile:*` had two independent owners before Phase 1 PR 6**: both keys were read *and written* by `apps/channels/models.py` and independently by `apps/proxy/live_proxy/`, with neither key in `RedisKeys`. As of PR 6 they are `RedisKeys.channel_stream` / `RedisKeys.stream_profile`, and Django is the only writer — `apps/channels/models.py` (`get_stream`/`release_stream`/`update_stream_profile`/`_release_stale_stream_assignment`) plus the channel-deleted fallback in `apps/proxy/next_source.py`'s `release_source()`, which runs in the API process, never in the relay — the relay reaches them only through `POST /api/relay/channels/<identifier>/next-source` and `/release`. The Python relay read them directly (`live_proxy/views.py`) on purpose — they are Django-owned keys, not relay state, so PR 7's "no control-plane code reads relay keys" never covered them — and stage 2d-4 deleted that reader. **Django is now the only process that touches either key at all**, which is the shape PR 6 was aiming at and did not reach: the Go relay learns the stream and profile from the `next-source` answer and never opens Redis.
+- **Every write to a provider-slot counter goes through one Lua script** (#513). `apps/m3u/connection_pool.py`'s `_SLOT_SCRIPT` reserves, releases, switches and reconciles `profile_connections:{id}` and `server_group_connections:{group}:{fp}`, and every write bumps `slot_version:<counter key>` in the same step. A direct `INCR`/`DECR`/`SET` on either family anywhere else moves a counter without moving its version, which is the one change the provider-slot reconciler cannot see; `Channel.update_stream_profile()`'s own pipeline was such a writer until #513. The script also makes both negative-counter repairs atomic (#470 on the credential counter, #471 on the profile counter) and checks both caps before writing either, so a refused reserve writes nothing where it used to `INCR` then `DECR`. In-memory test fakes run it through `apps/m3u/tests/slot_script_fake.py`, which `apps/m3u/tests/test_slot_script.py`'s `SlotScriptFakeParityTests` holds to the Lua on a live Redis.
 - **#190 is closed by deletion.** Stage 2d-4 removed all five of its ranges from `apps/channels/models.py` — three reads and two `hdel`s against `live:channel:<uuid>:metadata`, a key the Go relay never writes, so every read had returned `None` and every `hdel` had been a no-op since the 2d-3 cutover. What it described, for the record: **a control-plane write to the relay metadata hash on every successful `Channel.release_stream()`, plus THREE fallback-path reads** — `release_stream()`'s recovery branch, a second fallback read in the same method that CLAUDE.md never recorded, and `_release_stale_stream_assignment()`, which `get_stream()` calls and `release_stream()` does not ([#190](https://github.com/D10Scot/Dispatcharr/issues/190)). The `hdel` ran on **every** successful release, not only in a rare recovery branch, clearing `ChannelMetadataField.STREAM_ID`/`M3U_PROFILE` so a duplicate release could not `DECR` the provider counter twice — which is why the writes were never as easy as the reads and why this waited for the deletion rather than being fixed in place. Everything else — the reuse check, the DVR client scans, `fetch_channel_stats`, the recording metadata capture and the live branch of `get_user_active_connections` — goes through `apps/proxy/relay_client.py`.
 - **`get_user_active_connections` has five callers** — four more than the bullet said for most of its life, the fifth being `check_user_stream_limits` at `apps/proxy/utils.py:354`, which takes the `include_live=True` default and is the other live one. **One of them used to trigger a relay side effect on every call.** Three timeshift helpers (`_session_has_active_timeshift_stream`, `_preempt_playback_streams`, `_terminate_previous_timeshift_sessions`) pass `include_live=False` (`apps/proxy/utils.py`), added by a whole-branch-review fix after one of them — reached from `_serve_catchup`, a relay-served view — was making the relay call itself over HTTP per catch-up tune for a live client list it always discarded. The fourth caller, `apps/output/views.py`'s `xc_get_info` (the Xtream `player_api.php` handshake, every XC session), is deliberately left asking for the live count — `active_cons` needs it — so that call still reaches `GET /proxy/relay/channels?clients=all` on every handshake, and `get_basic_channel_info` there runs `ClientManager.remove_ghost_clients`, an `SREM` write across every running channel that the old direct Redis scan never performed. **That side effect is gone**, not fixed: the Go relay's client registry is a map in process memory (Phase 2 stage 2c-3), where a client entry cannot outlive the goroutine that made it, so `GET /proxy/relay/channels?clients=all` performs no write at all. `xc_get_info` still makes the call and still gets its `active_cons`; only the `SREM` across every running channel disappeared, at stage 2d-3's flip.
 - **The UDP user-agent filter no longer leaves dangling flags** ([#296](https://github.com/D10Scot/Dispatcharr/issues/296), fixed in #396): a dropped value takes the flag before it and a dropped flag the value after it, which also repairs the shipped Streamlink profile on a UDP upstream.
diff --git a/apps/channels/models.py b/apps/channels/models.py
index d6e93ad4..fab3305b 100644
--- a/apps/channels/models.py
+++ b/apps/channels/models.py
@@ -757,10 +757,7 @@ class Channel(models.Model):
         if current_profile_id == new_profile_id:
             return True
 
-        from apps.m3u.connection_pool import (
-            move_credential_slot_on_profile_switch,
-            profile_connections_key,
-        )
+        from apps.m3u.connection_pool import switch_profile_slot
         from apps.m3u.models import M3UAccountProfile
 
         old_profile = M3UAccountProfile.objects.select_related(
@@ -770,26 +767,23 @@ class Channel(models.Model):
             "m3u_account__server_group"
         ).get(id=new_profile_id)
 
-        if not move_credential_slot_on_profile_switch(
-            old_profile, new_profile, redis_client
+        # One script call moves both profile counters, the credential counter
+        # when the login changes, and the stream_profile key, bumping each
+        # counter's version as it writes it (#513): this used to be a
+        # credential move followed by its own DECR/SET/INCR pipeline, a
+        # counter writer outside reserve/release that the reconciler could
+        # not see.
+        if not switch_profile_slot(
+            old_profile,
+            new_profile,
+            RedisKeys.stream_profile(stream_id),
+            redis_client,
         ):
             logger.warning(
                 "Shared login pool full for profile %s during stream profile switch",
                 new_profile_id,
             )
             return False
-
-        # Profile counters always move on switch; credential totals move only when login changes.
-        old_profile_connections_key = profile_connections_key(current_profile_id)
-        new_profile_connections_key = profile_connections_key(new_profile_id)
-        old_count = int(redis_client.get(old_profile_connections_key) or 0)
-
-        pipe = redis_client.pipeline()
-        if old_count > 0:
-            pipe.decr(old_profile_connections_key)
-        pipe.set(RedisKeys.stream_profile(stream_id), new_profile_id)
-        pipe.incr(new_profile_connections_key)
-        pipe.execute()
         logger.info(
             f"Updated stream {stream_id} profile from {current_profile_id} to {new_profile_id}"
         )
diff --git a/apps/m3u/connection_pool.py b/apps/m3u/connection_pool.py
index d937e9a5..5d3132b4 100644
--- a/apps/m3u/connection_pool.py
+++ b/apps/m3u/connection_pool.py
@@ -195,138 +195,273 @@ def profile_available_for_channel_switch(
     return pool_has_capacity_for_profile(profile, redis_client)
 
 
-def move_credential_slot_on_profile_switch(
-    old_profile, new_profile, redis_client
-) -> bool:
-    """
-    Move the shared credential counter when switching to a different provider login.
-
-    Profile counters are managed separately by Channel.update_stream_profile().
-    Returns False when the new profile's credential pool is full.
-    """
-    old_fp = get_profile_credential_fingerprint(old_profile)
-    new_fp = get_profile_credential_fingerprint(new_profile)
-    if old_fp == new_fp:
-        return True
-
-    _release_credential_slot_by_profile_id(old_profile.id, redis_client)
-
-    cred_reserved, cred_key = _reserve_server_group_slot_for_profile(
-        new_profile, redis_client
-    )
-    if not cred_reserved:
-        restore_reserved, restore_key = _reserve_server_group_slot_for_profile(
-            old_profile, redis_client
-        )
-        if restore_reserved and restore_key:
-            _remember_credential_release_key(
-                old_profile.id, restore_key, redis_client
-            )
-        return False
+# --------------------------------------------------------------------------
+# The provider-slot script (#513 constraint 1; #470; #471).
+#
+# EVERY write to a provider-slot counter -- profile_connections:{id} and
+# server_group_connections:{group}:{fp} -- happens inside this one Lua script,
+# and every such write increments slot_version:<counter key> in the same
+# atomic step. The reconciler (apps/proxy/slot_reconciler.py) reads a
+# counter's version at one run and writes the counter at the next only if the
+# version has not moved, so "unchanged" means "nobody wrote it", never "it was
+# written and written back" (a release then a tune between runs).
+#
+# The script also makes both repairs atomic that were a GET then a SET in
+# Python: a counter found below zero is treated as zero by a reserve and set
+# to zero by a release (#470 for the credential counter, #471 for the profile
+# counter). A reserve checks both caps BEFORE writing either counter, so a
+# refused reserve writes nothing at all -- no INCR-then-DECR -- and bumps no
+# version.
+#
+# The one key this script touches without it being passed in KEYS is the
+# credential counter a release pointer names (profile_credential_release:{id}
+# stores it at reserve time). That is fine on the single, non-cluster Redis
+# every deployment runs, and it is the reason release does not need an ORM
+# read to find the counter (PoolEnforcementTests pins that).
+# --------------------------------------------------------------------------
+SLOT_VERSION_KEY_PREFIX = "slot_version:"
+
+_SLOT_SCRIPT = """
+-- provider_slot
+local op = ARGV[1]
+
+local function vkey(k) return 'slot_version:' .. k end
+local function read(k) return tonumber(redis.call('GET', k) or '0') or 0 end
+local function write(k, v)
+  redis.call('SET', k, v)
+  redis.call('INCR', vkey(k))
+end
+-- Give one slot back: never below zero; a counter already below zero is
+-- repaired to zero; an absent or zero counter is left alone.
+local function give_back(k)
+  local c = read(k)
+  if c > 0 then
+    write(k, c - 1)
+  elseif c < 0 then
+    write(k, 0)
+  end
+end
+-- Take one slot with no cap (a profile switch): a negative counter counts from zero.
+local function take(k)
+  local c = read(k)
+  if c < 0 then c = 0 end
+  write(k, c + 1)
+end
+
+if op == 'reserve' then
+  -- KEYS: profile counter, credential counter (or a placeholder), release pointer
+  -- ARGV: op, profile max (0 = not counted), credential max (0 = no credential counter)
+  local pmax = tonumber(ARGV[2])
+  local cmax = tonumber(ARGV[3])
+  local pc = 0
+  if pmax > 0 then
+    pc = read(KEYS[1])
+    if pc < 0 then pc = 0 end
+    if pc + 1 > pmax then return {0, pc, 'profile_full'} end
+  end
+  local cc = 0
+  if cmax > 0 then
+    cc = read(KEYS[2])
+    if cc < 0 then cc = 0 end
+    if cc + 1 > cmax then return {0, pc, 'credential_full'} end
+  end
+  if pmax > 0 then write(KEYS[1], pc + 1) end
+  if cmax > 0 then
+    write(KEYS[2], cc + 1)
+    redis.call('SET', KEYS[3], KEYS[2])
+  end
+  if pmax > 0 then return {1, pc + 1, ''} end
+  return {1, 0, ''}
+elseif op == 'release' then
+  -- KEYS: profile counter, release pointer
+  local ck = redis.call('GET', KEYS[2])
+  if ck then
+    give_back(ck)
+    redis.call('DEL', KEYS[2])
+  end
+  give_back(KEYS[1])
+  if ck then return 1 end
+  return 0
+elseif op == 'switch' then
+  -- KEYS: old profile counter, new profile counter, stream_profile key,
+  --       old release pointer, new release pointer, new credential counter
+  -- ARGV: op, new profile id, move credential (0/1), new credential max
+  if ARGV[3] == '1' then
+    local ncmax = tonumber(ARGV[4])
+    local ncc = 0
+    if ncmax > 0 then
+      ncc = read(KEYS[6])
+      if ncc < 0 then ncc = 0 end
+      if ncc + 1 > ncmax then return {0, 'credential_full'} end
+    end
+    local ock = redis.call('GET', KEYS[4])
+    if ock then
+      give_back(ock)
+      redis.call('DEL', KEYS[4])
+    end
+    if ncmax > 0 then
+      write(KEYS[6], ncc + 1)
+      redis.call('SET', KEYS[5], KEYS[6])
+    end
+  end
+  give_back(KEYS[1])
+  redis.call('SET', KEYS[3], ARGV[2])
+  take(KEYS[2])
+  return {1, ''}
+elseif op == 'reconcile' then
+  -- KEYS: counter. ARGV: op, expected version, floor, ceiling.
+  -- Writes the counter, clamped into [floor, ceiling], only if its version
+  -- still equals the one the previous reconciler run recorded. The
+  -- reconciler's own write bumps no version: it is not a holder.
+  local k = KEYS[1]
+  local v = tonumber(redis.call('GET', vkey(k)) or '0') or 0
+  local c = read(k)
+  if v ~= tonumber(ARGV[2]) then return {-1, c, c} end
+  local t = c
+  local lo = tonumber(ARGV[3])
+  local hi = tonumber(ARGV[4])
+  if t < lo then t = lo end
+  if t > hi then t = hi end
+  if t == c then return {0, c, c} end
+  redis.call('SET', k, t)
+  return {1, c, t}
+end
+return redis.error_reply('provider_slot: unknown op ' .. tostring(op))
+"""
 
-    if cred_key:
-        _remember_credential_release_key(new_profile.id, cred_key, redis_client)
-    return True
+# A placeholder for an unused KEYS slot: the script never reads or writes it
+# (every use of KEYS[2] in 'reserve' is guarded by cmax > 0, and of KEYS[6] in
+# 'switch' by ncmax > 0).
+_NO_KEY = "provider_slot:unused"
 
 
-def _safe_decr(redis_client, key: str) -> None:
-    current = int(redis_client.get(key) or 0)
-    if current <= 0:
-        if current < 0:
-            # A drifted-negative counter (no TTL) would otherwise stay negative
-            # and admit streams past max_streams; repair it on sight.
-            redis_client.set(key, 0)
-        return
-    new_count = redis_client.decr(key)
-    if new_count < 0:
-        redis_client.set(key, 0)
+def slot_version_key(counter_key: str) -> str:
+    """The version key the slot script bumps on every write to counter_key."""
+    return f"{SLOT_VERSION_KEY_PREFIX}{counter_key}"
 
 
-def _remember_credential_release_key(
-    profile_id: int, cred_key: str, redis_client
-) -> None:
-    redis_client.set(profile_credential_release_key(profile_id), cred_key)
+def _run_slot_script(redis_client, keys, args):
+    # register_script() only hashes the source; the first call per server
+    # loads it and every later call is one EVALSHA. No per-client cache: a
+    # cache keyed on id(client) can hand a new client a stale Script bound to
+    # a dead one (the VOD module's tests clear such a cache for that reason).
+    return redis_client.register_script(_SLOT_SCRIPT)(keys=keys, args=args)
 
 
-def _release_credential_slot_by_profile_id(profile_id: int, redis_client) -> bool:
-    """Release a reserved credential counter using the key stored at reserve time."""
-    release_key = profile_credential_release_key(profile_id)
-    cred_key = redis_client.get(release_key)
-    if not cred_key:
-        return False
+def _decoded(value):
+    return value.decode() if isinstance(value, bytes) else value
 
-    if isinstance(cred_key, bytes):
-        cred_key = cred_key.decode()
-    _safe_decr(redis_client, cred_key)
-    redis_client.delete(release_key)
-    return True
 
+def credential_reservation(profile) -> Tuple[Optional[str], int]:
+    """The credential counter a reserve on this profile counts against, and its cap.
 
-def _reserve_server_group_slot_for_profile(
-    profile, redis_client
-) -> Tuple[bool, Optional[str]]:
+    (None, 0) when the profile skips credential enforcement: no ServerGroup,
+    max_streams=0, or no fingerprint.
+    """
     group = get_enforced_server_group_for_profile(profile)
     if not group or profile.max_streams == 0:
-        return True, None
-
+        return None, 0
     cred_key = _credential_counter_key(profile, group)
     if not cred_key:
-        return True, None
-
-    cred_count = redis_client.incr(cred_key)
-    if cred_count < 1:
-        # The counter was negative before this reservation; count this stream
-        # once and discard the drift so the cap applies from here on.
-        redis_client.set(cred_key, 1)
-        cred_count = 1
-    if cred_count <= profile.max_streams:
-        return True, cred_key
-
-    redis_client.decr(cred_key)
-    return False, None
+        return None, 0
+    return cred_key, profile.max_streams
 
 
 def reserve_profile_slot(
     profile, redis_client
 ) -> Tuple[bool, int, Optional[ReserveFailureReason]]:
     """
-    Atomically reserve profile + optional credential slots (INCR-first).
+    Atomically reserve profile + optional credential slots in one script call.
 
     Returns (reserved, profile_count_after_attempt, failure_reason).
-    failure_reason is set when reserved is False.
+    failure_reason is set when reserved is False. A refused reserve writes
+    nothing.
     """
-    profile_key = profile_connections_key(profile.id)
-    profile_count = 0
+    cred_key, cred_max = credential_reservation(profile)
+    result = _run_slot_script(
+        redis_client,
+        keys=[
+            profile_connections_key(profile.id),
+            cred_key or _NO_KEY,
+            profile_credential_release_key(profile.id),
+        ],
+        args=["reserve", max(profile.max_streams, 0), cred_max],
+    )
+    reserved, count, reason = int(result[0]), int(result[1]), _decoded(result[2])
+    if reserved:
+        return True, count, None
+    return False, count, reason
 
-    if profile.max_streams > 0:
-        profile_count = redis_client.incr(profile_key)
-        if profile_count > profile.max_streams:
-            redis_client.decr(profile_key)
-            return False, profile_count - 1, "profile_full"
 
-    cred_reserved, cred_key = _reserve_server_group_slot_for_profile(
-        profile, redis_client
+def release_profile_slot(profile_id: int, redis_client) -> None:
+    """Release profile and shared credential slots after a stream end."""
+    _run_slot_script(
+        redis_client,
+        keys=[
+            profile_connections_key(profile_id),
+            profile_credential_release_key(profile_id),
+        ],
+        args=["release"],
     )
-    if not cred_reserved:
-        if profile.max_streams > 0:
-            redis_client.decr(profile_key)
-        return (
-            False,
-            profile_count - 1 if profile.max_streams > 0 else 0,
-            "credential_full",
-        )
 
-    if cred_key:
-        _remember_credential_release_key(profile.id, cred_key, redis_client)
 
-    return True, profile_count, None
+def switch_profile_slot(
+    old_profile, new_profile, stream_profile_key: str, redis_client
+) -> bool:
+    """Move one stream's slots from old_profile to new_profile, atomically.
 
+    The profile counters always move: old gives one back, new takes one with
+    no cap check (the caller selected new_profile with
+    profile_available_for_channel_switch() first, exactly as before). The
+    credential counter moves only when the provider login changes, and a full
+    credential pool on the new login refuses the whole switch before anything
+    is written. stream_profile_key is rewritten to new_profile's id in the
+    same step.
+
+    Returns False when the new login's credential pool is full.
+    """
+    old_fp = get_profile_credential_fingerprint(old_profile)
+    new_fp = get_profile_credential_fingerprint(new_profile)
+    move_credential = old_fp != new_fp
+    new_cred_key, new_cred_max = (
+        credential_reservation(new_profile) if move_credential else (None, 0)
+    )
+    result = _run_slot_script(
+        redis_client,
+        keys=[
+            profile_connections_key(old_profile.id),
+            profile_connections_key(new_profile.id),
+            stream_profile_key,
+            profile_credential_release_key(old_profile.id),
+            profile_credential_release_key(new_profile.id),
+            new_cred_key or _NO_KEY,
+        ],
+        args=["switch", new_profile.id, 1 if move_credential else 0, new_cred_max],
+    )
+    return int(result[0]) == 1
+
+
+def reconcile_counter(
+    counter_key: str, expected_version: int, floor: int, ceiling: int, redis_client
+) -> Tuple[int, int, int]:
+    """Clamp a counter into [floor, ceiling] if its version is still expected_version.
+
+    Returns (status, before, after): status -1 when the version moved (no
+    write), 0 when the counter was already inside the range (no write), 1 when
+    it was written.
+    """
+    result = _run_slot_script(
+        redis_client,
+        keys=[counter_key],
+        args=["reconcile", expected_version, floor, ceiling],
+    )
+    return int(result[0]), int(result[1]), int(result[2])
 
-def release_profile_slot(profile_id: int, redis_client) -> None:
-    """Release profile and shared credential slots after a stream end."""
-    _release_credential_slot_by_profile_id(profile_id, redis_client)
 
-    profile_key = profile_connections_key(profile_id)
-    current = int(redis_client.get(profile_key) or 0)
-    if current > 0:
-        redis_client.decr(profile_key)
+def read_slot_versions(counter_keys, redis_client) -> dict:
+    """One MGET of every counter's version; an absent version reads 0."""
+    counter_keys = list(counter_keys)
+    if not counter_keys:
+        return {}
+    values = redis_client.mget([slot_version_key(k) for k in counter_keys])
+    return {k: int(_decoded(v) or 0) for k, v in zip(counter_keys, values)}
diff --git a/apps/m3u/tests/slot_script_fake.py b/apps/m3u/tests/slot_script_fake.py
new file mode 100644
index 00000000..efdd1407
--- /dev/null
+++ b/apps/m3u/tests/slot_script_fake.py
@@ -0,0 +1,127 @@
+"""An in-memory stand-in for apps/m3u/connection_pool.py's provider-slot Lua script.
+
+connection_pool runs every counter write through one Lua script (#513). The
+in-memory Redis fakes several test modules use cannot run Lua, so they gain
+``register_script`` from ``SlotScriptFakeMixin`` below, which answers the
+script's four ops in Python on top of the fake's own ``get``/``set``/``delete``.
+
+This is a second implementation of the script, and a second implementation
+proves only itself. It is kept honest by
+``apps/m3u/tests/test_slot_script.py``'s ``SlotScriptFakeParityTests``, which
+drives the same operation sequences through the real Lua on a live Redis and
+through this class, and requires identical returns and identical final state.
+Atomicity is NOT something this fake can show: the real-Redis tests in that
+module are what pin it.
+
+Test routing: ``dispatcharr/test_discovery.py``'s ``_PATH_ALIASES`` sends an
+edit to this file to every label whose fakes import it, because a change here
+can break a label the edit never touches.
+"""
+
+from apps.m3u.connection_pool import _SLOT_SCRIPT, SLOT_VERSION_KEY_PREFIX
+
+
+def _text(value):
+    if isinstance(value, bytes):
+        return value.decode()
+    return value
+
+
+class _FakeSlotScript:
+    def __init__(self, redis):
+        self._redis = redis
+
+    def _read(self, key):
+        value = _text(self._redis.get(key))
+        try:
+            return int(value) if value is not None else 0
+        except (TypeError, ValueError):
+            return 0
+
+    def _write(self, key, value):
+        self._redis.set(key, value)
+        vkey = SLOT_VERSION_KEY_PREFIX + key
+        self._redis.set(vkey, self._read(vkey) + 1)
+
+    def _give_back(self, key):
+        current = self._read(key)
+        if current > 0:
+            self._write(key, current - 1)
+        elif current < 0:
+            self._write(key, 0)
+
+    def _take(self, key):
+        current = max(self._read(key), 0)
+        self._write(key, current + 1)
+
+    def __call__(self, keys=(), args=(), client=None):
+        keys = list(keys)
+        args = [str(a) for a in args]
+        op = args[0]
+        if op == "reserve":
+            pmax, cmax = int(args[1]), int(args[2])
+            pc = 0
+            if pmax > 0:
+                pc = max(self._read(keys[0]), 0)
+                if pc + 1 > pmax:
+                    return [0, pc, "profile_full"]
+            cc = 0
+            if cmax > 0:
+                cc = max(self._read(keys[1]), 0)
+                if cc + 1 > cmax:
+                    return [0, pc, "credential_full"]
+            if pmax > 0:
+                self._write(keys[0], pc + 1)
+            if cmax > 0:
+                self._write(keys[1], cc + 1)
+                self._redis.set(keys[2], keys[1])
+            return [1, pc + 1 if pmax > 0 else 0, ""]
+        if op == "release":
+            cred_key = _text(self._redis.get(keys[1]))
+            if cred_key:
+                self._give_back(cred_key)
+                self._redis.delete(keys[1])
+            self._give_back(keys[0])
+            return 1 if cred_key else 0
+        if op == "switch":
+            if args[2] == "1":
+                ncmax = int(args[3])
+                ncc = 0
+                if ncmax > 0:
+                    ncc = max(self._read(keys[5]), 0)
+                    if ncc + 1 > ncmax:
+                        return [0, "credential_full"]
+                old_cred_key = _text(self._redis.get(keys[3]))
+                if old_cred_key:
+                    self._give_back(old_cred_key)
+                    self._redis.delete(keys[3])
+                if ncmax > 0:
+                    self._write(keys[5], ncc + 1)
+                    self._redis.set(keys[4], keys[5])
+            self._give_back(keys[0])
+            self._redis.set(keys[2], args[1])
+            self._take(keys[1])
+            return [1, ""]
+        if op == "reconcile":
+            key = keys[0]
+            version = self._read(SLOT_VERSION_KEY_PREFIX + key)
+            current = self._read(key)
+            if version != int(args[1]):
+                return [-1, current, current]
+            target = min(max(current, int(args[2])), int(args[3]))
+            if target == current:
+                return [0, current, current]
+            self._redis.set(key, target)
+            return [1, current, target]
+        raise ValueError(f"provider_slot: unknown op {op}")
+
+
+class SlotScriptFakeMixin:
+    """Gives an in-memory Redis fake the one ``register_script`` connection_pool needs."""
+
+    def register_script(self, source):
+        if source != _SLOT_SCRIPT:
+            raise NotImplementedError(
+                "SlotScriptFakeMixin answers only connection_pool's slot script"
+            )
+        return _FakeSlotScript(self)
diff --git a/apps/m3u/tests/test_connection_pool.py b/apps/m3u/tests/test_connection_pool.py
index c45210bc..4560e62b 100644
--- a/apps/m3u/tests/test_connection_pool.py
+++ b/apps/m3u/tests/test_connection_pool.py
@@ -4,7 +4,6 @@ from django.test import TestCase
 from unittest.mock import patch
 
 from apps.m3u.connection_pool import (
-    _safe_decr,
     compute_credential_fingerprint,
     extract_credentials_from_stream_url,
     get_credential_connection_count,
@@ -21,9 +20,10 @@ from apps.m3u.connection_pool import (
     server_group_connections_key,
 )
 from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
 
 
-class FakeRedis:
+class FakeRedis(SlotScriptFakeMixin):
     """Minimal in-memory Redis stand-in for counter tests."""
 
     def __init__(self):
@@ -620,21 +620,23 @@ class CredentialFingerprintCasefoldTests(TestCase):
 
 class CredentialCounterRepairTests(TestCase):
     """#146: a credential counter that has drifted below zero (no TTL) must
-    be repaired on sight, both on release (_safe_decr) and on reserve (the
-    INCR-first path in _reserve_server_group_slot_for_profile), or the
-    ServerGroup cap stays lifted until the counter climbs back past zero on
-    its own."""
+    be repaired on sight, both on release and on reserve, or the ServerGroup
+    cap stays lifted until the counter climbs back past zero on its own.
+    Both repairs are inside connection_pool's slot script since #513 (the
+    _safe_decr helper this class once called directly went into it)."""
 
-    def test_safe_decr_repairs_a_counter_already_below_zero(self):
+    def test_release_repairs_a_credential_counter_already_below_zero(self):
         redis = FakeRedis()
 
         redis.set("negative_one", -1)
-        _safe_decr(redis, "negative_one")
+        redis.set(profile_credential_release_key(1), "negative_one")
+        release_profile_slot(1, redis)
         self.assertEqual(int(redis.get("negative_one")), 0)
 
         # The issue's own counterexample.
         redis.set("negative_three", -3)
-        _safe_decr(redis, "negative_three")
+        redis.set(profile_credential_release_key(2), "negative_three")
+        release_profile_slot(2, redis)
         self.assertEqual(int(redis.get("negative_three")), 0)
 
     def test_negative_credential_counter_does_not_lift_the_cap(self):
diff --git a/apps/m3u/tests/test_property_connection_pool.py b/apps/m3u/tests/test_property_connection_pool.py
index 5a23836c..bd8e157b 100644
--- a/apps/m3u/tests/test_property_connection_pool.py
+++ b/apps/m3u/tests/test_property_connection_pool.py
@@ -25,8 +25,8 @@ from django.test import SimpleTestCase
 from hypothesis import example, given, settings as hyp_settings, strategies as st
 
 from apps.m3u import connection_pool
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
 from apps.m3u.connection_pool import (
-    _safe_decr,
     profile_connections_key,
     release_profile_slot,
     reserve_profile_slot,
@@ -47,7 +47,7 @@ GROUP_ID = 7
 CRED_KEY = server_group_connections_key(GROUP_ID, FINGERPRINT)
 
 
-class FakeRedis:
+class FakeRedis(SlotScriptFakeMixin):
     """In-memory stand-in for the five commands connection_pool uses."""
 
     def __init__(self, data=None):
@@ -96,10 +96,13 @@ class SafeDecrProperties(SimpleTestCase):
     @given(start=st.none() | st.integers(min_value=-10, max_value=20))
     @example(start=-1)  # #146: shrunk counterexample, left at -1.
     @example(start=-3)  # #146: the issue's drifted credential counter.
-    def test_safe_decr_lands_on_one_less_but_never_below_zero(self, start):
-        redis = FakeRedis({} if start is None else {"k": start})
-        _safe_decr(redis, "k")
-        self.assertEqual(redis.count("k"), max((start or 0) - 1, 0))
+    def test_a_release_lands_one_less_but_never_below_zero(self, start):
+        # _safe_decr went into connection_pool's slot script (#513); a release
+        # with no credential pointer gives back exactly the profile counter.
+        key = profile_connections_key(1)
+        redis = FakeRedis({} if start is None else {key: start})
+        release_profile_slot(1, redis)
+        self.assertEqual(redis.count(key), max((start or 0) - 1, 0))
 
 
 class ReserveProfileSlotProperties(SimpleTestCase):
diff --git a/apps/m3u/tests/test_slot_script.py b/apps/m3u/tests/test_slot_script.py
new file mode 100644
index 00000000..3b7689e4
--- /dev/null
+++ b/apps/m3u/tests/test_slot_script.py
@@ -0,0 +1,473 @@
+"""The provider-slot Lua script, against a live Redis (#513 constraint 1; #470; #471).
+
+Every write to profile_connections:{id} and server_group_connections:{g}:{fp}
+goes through connection_pool's one script, and every such write bumps
+slot_version:<counter> in the same step. These tests run the real script on
+the Redis the suite already uses (the same client TestVodActiveStreamsRealRedis
+reaches), because atomicity is the property under test and an in-memory fake
+cannot show it.
+
+Without Redis they skip -- except under CI, where a missing Redis is a broken
+environment and the class fails instead, the way relay/channel's real-ffmpeg
+pin fails rather than skips when CI is set.
+"""
+
+from __future__ import annotations
+
+import os
+import threading
+import uuid
+from types import SimpleNamespace
+from unittest import mock
+
+from django.test import SimpleTestCase
+from hypothesis import given, settings as hyp_settings, strategies as st
+
+from apps.m3u import connection_pool
+from apps.m3u.connection_pool import (
+    profile_connections_key,
+    profile_credential_release_key,
+    read_slot_versions,
+    reconcile_counter,
+    release_profile_slot,
+    reserve_profile_slot,
+    slot_version_key,
+    switch_profile_slot,
+)
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
+
+# CI-deterministic profile, byte-identical to tests/test_redaction.py's.
+hyp_settings.register_profile(
+    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
+)
+hyp_settings.load_profile("dispatcharr-ci")
+
+
+def live_redis():
+    from core.utils import RedisClient
+
+    try:
+        client = RedisClient.get_client(max_retries=1, retry_interval=0)
+        if client is not None and client.ping():
+            return client
+    except Exception:
+        pass
+    return None
+
+
+class LiveRedisTestCase(SimpleTestCase):
+    """A per-test key namespace on the live Redis, deleted afterwards."""
+
+    redis = None
+
+    @classmethod
+    def setUpClass(cls):
+        super().setUpClass()
+        cls.redis = live_redis()
+
+    def setUp(self):
+        if self.redis is None:
+            if os.environ.get("CI"):
+                self.fail("Redis is not reachable under CI: these tests must run, not skip")
+            self.skipTest("Redis not available")
+        # Profile ids and group ids from a range no fixture uses, per test.
+        self.base = 900_000 + (uuid.uuid4().int % 90_000) * 10
+
+    def tearDown(self):
+        if self.redis is None:
+            return
+        for pattern in (
+            f"*profile_connections:{self.base}*",
+            f"*server_group_connections:{self.base}:*",
+            f"profile_credential_release:{self.base}*",
+            f"stream_profile:{self.base}*",
+        ):
+            keys = list(self.redis.scan_iter(match=pattern, count=1000))
+            if keys:
+                self.redis.delete(*keys)
+
+    def profile(self, offset, max_streams, *, login=None):
+        """A profile stand-in: in ServerGroup `self.base` when login is set."""
+        return SimpleNamespace(
+            id=self.base + offset,
+            pk=self.base + offset,
+            max_streams=max_streams,
+            login=login,
+        )
+
+    def cred_key(self, login):
+        return f"server_group_connections:{self.base}:{login}"
+
+    def patched_logins(self):
+        """Resolve the credential counter from the stand-in's `login`, no ORM."""
+        return mock.patch.multiple(
+            connection_pool,
+            get_enforced_server_group_for_profile=lambda p: (
+                SimpleNamespace(id=self.base) if p.login else None
+            ),
+            _credential_counter_key=lambda p, g: self.cred_key(p.login),
+            get_profile_credential_fingerprint=lambda p: p.login,
+        )
+
+    def value(self, key):
+        raw = self.redis.get(key)
+        return None if raw is None else int(raw)
+
+    def version(self, key):
+        return int(self.redis.get(slot_version_key(key)) or 0)
+
+
+class SlotScriptVersionTests(LiveRedisTestCase):
+    """Every counter write bumps that counter's version, and nothing else does."""
+
+    def test_each_write_bumps_the_version_of_the_counter_it_writes(self):
+        p = self.profile(1, 2, login="a")
+        pk, ck = profile_connections_key(p.id), self.cred_key("a")
+        with self.patched_logins():
+            self.assertEqual(reserve_profile_slot(p, self.redis), (True, 1, None))
+            self.assertEqual((self.version(pk), self.version(ck)), (1, 1))
+            release_profile_slot(p.id, self.redis)
+            self.assertEqual((self.value(pk), self.value(ck)), (0, 0))
+            self.assertEqual((self.version(pk), self.version(ck)), (2, 2))
+            # A release with nothing held writes nothing and bumps nothing.
+            release_profile_slot(p.id, self.redis)
+            self.assertEqual((self.version(pk), self.version(ck)), (2, 2))
+
+    def test_a_refused_reserve_writes_nothing_and_bumps_nothing(self):
+        p = self.profile(1, 1, login="a")
+        q = self.profile(2, 1, login="a")  # same login, room of its own
+        pk, qk, ck = (
+            profile_connections_key(p.id),
+            profile_connections_key(q.id),
+            self.cred_key("a"),
+        )
+        with self.patched_logins():
+            self.assertTrue(reserve_profile_slot(p, self.redis)[0])
+            before = {k: (self.value(k), self.version(k)) for k in (pk, qk, ck)}
+            self.assertEqual(reserve_profile_slot(p, self.redis), (False, 1, "profile_full"))
+            self.assertEqual(reserve_profile_slot(q, self.redis), (False, 0, "credential_full"))
+            after = {k: (self.value(k), self.version(k)) for k in (pk, qk, ck)}
+        self.assertEqual(after, before, "a refused reserve wrote a counter or moved a version")
+
+    def test_a_switch_bumps_both_profile_versions_in_one_step(self):
+        old, new = self.profile(1, 2, login="a"), self.profile(2, 2, login="b")
+        ok, nk = profile_connections_key(old.id), profile_connections_key(new.id)
+        sp = f"stream_profile:{self.base}7"
+        with self.patched_logins():
+            reserve_profile_slot(old, self.redis)
+            self.assertTrue(switch_profile_slot(old, new, sp, self.redis))
+        self.assertEqual((self.value(ok), self.value(nk)), (0, 1))
+        self.assertEqual((self.version(ok), self.version(nk)), (2, 1))
+        self.assertEqual((self.value(self.cred_key("a")), self.value(self.cred_key("b"))), (0, 1))
+        self.assertEqual(self.redis.get(sp), str(new.id))
+        self.assertEqual(
+            self.redis.get(profile_credential_release_key(new.id)), self.cred_key("b")
+        )
+
+    def test_a_switch_refused_by_the_new_login_writes_nothing(self):
+        old, new = self.profile(1, 2, login="a"), self.profile(2, 1, login="b")
+        sp = f"stream_profile:{self.base}7"
+        with self.patched_logins():
+            reserve_profile_slot(old, self.redis)
+            self.redis.set(self.cred_key("b"), 1)
+            watched = [
+                profile_connections_key(old.id),
+                profile_connections_key(new.id),
+                self.cred_key("a"),
+                self.cred_key("b"),
+                profile_credential_release_key(old.id),
+                sp,
+            ]
+            before = {k: (self.redis.get(k), self.version(k)) for k in watched}
+            self.assertFalse(switch_profile_slot(old, new, sp, self.redis))
+            after = {k: (self.redis.get(k), self.version(k)) for k in watched}
+        self.assertEqual(after, before)
+
+
+class SlotScriptRepairTests(LiveRedisTestCase):
+    """#471 on the profile counter, #470 on the credential counter."""
+
+    def test_a_negative_profile_counter_does_not_lift_max_streams(self):
+        # #471: at the seed the INCR-first check admitted from -3 against a cap of 1.
+        p = self.profile(1, 1)
+        pk = profile_connections_key(p.id)
+        self.redis.set(pk, -3)
+        with self.patched_logins():
+            results = [reserve_profile_slot(p, self.redis)[0] for _ in range(3)]
+        self.assertEqual(results, [True, False, False], "a negative profile counter lifted the cap (#471)")
+        self.assertEqual(self.value(pk), 1)
+
+    def test_a_release_repairs_a_negative_profile_counter(self):
+        # #471: at the seed `if current > 0` left it negative forever.
+        pk = profile_connections_key(self.base + 1)
+        self.redis.set(pk, -2)
+        release_profile_slot(self.base + 1, self.redis)
+        self.assertEqual(self.value(pk), 0)
+
+    def _interleaved(self, first, second, hook_key, hook_op):
+        """Run `first` and `second` on two threads, pausing `first` right after
+        its `hook_op` on `hook_key` until `second` has finished. The seed's
+        Python reserve/release have a gap there; the script has none, so
+        under the script the hook never fires and the two simply serialise."""
+        real = self.redis
+        paused = threading.Event()
+        resume = threading.Event()
+
+        class Hooked:
+            def __init__(self, owner):
+                self._owner = owner
+
+            def __getattr__(self, name):
+                attr = getattr(real, name)
+                if name != hook_op:
+                    return attr
+
+                def hooked(key, *a, **kw):
+                    out = attr(key, *a, **kw)
+                    if key == hook_key and threading.current_thread().name == "first":
+                        paused.set()
+                        resume.wait(5)
+                    return out
+
+                return hooked
+
+        results = {}
+        t1 = threading.Thread(target=lambda: results.update(first=first(Hooked(self))), name="first")
+        t1.start()
+        paused.wait(0.5)  # under the script nothing pauses; under the seed this is the gap
+        results["second"] = second(real)
+        resume.set()
+        t1.join(5)
+        return results
+
+    def test_470_reserve_side_race_admits_one_stream_from_minus_one_with_a_cap_of_one(self):
+        # #470's first interleaving: A INCRs to 0, B INCRs to 1 and is admitted,
+        # A SETs 1 and is also admitted -- two streams against a cap of one.
+        a, b = self.profile(1, 1, login="a"), self.profile(2, 1, login="a")
+        ck = self.cred_key("a")
+        self.redis.set(ck, -1)
+        with self.patched_logins():
+            results = self._interleaved(
+                lambda r: reserve_profile_slot(a, r)[0],
+                lambda r: reserve_profile_slot(b, r)[0],
+                hook_key=ck,
+                hook_op="incr",
+            )
+        admitted = [results["first"], results["second"]].count(True)
+        self.assertEqual(admitted, 1, f"{admitted} streams admitted against a cap of one (#470)")
+        self.assertEqual(self.value(ck), 1)
+
+    def test_470_release_side_race_leaves_the_counter_equal_to_the_streams_held(self):
+        # #470's second interleaving: the releaser reads -2, two reserves repair
+        # and are admitted, then the releaser SETs 0 -- two live streams, counter 0.
+        r_prof = self.profile(1, 5, login="a")
+        x, y = self.profile(2, 5, login="a"), self.profile(3, 5, login="a")
+        ck = self.cred_key("a")
+        self.redis.set(ck, -2)
+        self.redis.set(profile_credential_release_key(r_prof.id), ck)
+
+        def two_reserves(r):
+            return [reserve_profile_slot(x, r)[0], reserve_profile_slot(y, r)[0]]
+
+        with self.patched_logins():
+            results = self._interleaved(
+                lambda r: release_profile_slot(r_prof.id, r),
+                two_reserves,
+                hook_key=ck,
+                hook_op="get",
+            )
+        self.assertEqual(results["second"], [True, True])
+        self.assertEqual(self.value(ck), 2, "a release lost two live streams from the count (#470)")
+
+
+class ReconcileOpTests(LiveRedisTestCase):
+    """The op the reconciler writes through: a version-guarded clamp."""
+
+    def test_a_moved_version_blocks_the_write(self):
+        p = self.profile(1, 5)
+        pk = profile_connections_key(p.id)
+        with self.patched_logins():
+            reserve_profile_slot(p, self.redis)
+            seen = read_slot_versions([pk], self.redis)[pk]
+            release_profile_slot(p.id, self.redis)
+            reserve_profile_slot(p, self.redis)  # 1 -> 0 -> 1: same value, new version
+        self.assertEqual(reconcile_counter(pk, seen, 0, 0, self.redis), (-1, 1, 1))
+        self.assertEqual(self.value(pk), 1)
+
+    def test_an_unmoved_version_clamps_and_does_not_bump(self):
+        pk = profile_connections_key(self.base + 1)
+        self.redis.set(pk, 4)
+        seen = read_slot_versions([pk], self.redis)[pk]
+        self.assertEqual(reconcile_counter(pk, seen, 1, 2, self.redis), (1, 4, 2))
+        self.assertEqual(reconcile_counter(pk, seen, 0, 3, self.redis), (0, 2, 2))
+        self.assertEqual(reconcile_counter(pk, seen, 3, 5, self.redis), (1, 2, 3))
+        self.assertEqual(self.version(pk), seen)
+
+    def test_an_absent_counter_clamped_to_zero_is_not_created(self):
+        pk = profile_connections_key(self.base + 1)
+        self.assertEqual(reconcile_counter(pk, 0, 0, 0, self.redis), (0, 0, 0))
+        self.assertIsNone(self.redis.get(pk))
+
+
+class _DictRedis(SlotScriptFakeMixin):
+    """The smallest fake the shim runs on: string values, like a decoded client."""
+
+    def __init__(self):
+        self.data = {}
+
+    def get(self, key):
+        return self.data.get(key)
+
+    def set(self, key, value, ex=None):
+        self.data[key] = str(value)
+
+    def delete(self, key):
+        self.data.pop(key, None)
+
+
+class SlotScriptFakeParityTests(LiveRedisTestCase):
+    """slot_script_fake.py must answer exactly as the Lua does.
+
+    The same sequence runs through the real script on Redis and through the
+    fake, from the same starting values, and both the returns and every key's
+    final value must match.
+    """
+
+    def _run(self, client, steps):
+        a, b, c = self.profile(1, 2, login="a"), self.profile(2, 1, login="b"), self.profile(3, 0)
+        profiles = {"a": a, "b": b, "c": c}
+        out = []
+        with self.patched_logins():
+            for step in steps:
+                op, *rest = step
+                if op == "reserve":
+                    out.append(reserve_profile_slot(profiles[rest[0]], client))
+                elif op == "release":
+                    release_profile_slot(profiles[rest[0]].id, client)
+                    out.append(None)
+                elif op == "switch":
+                    out.append(switch_profile_slot(
+                        profiles[rest[0]], profiles[rest[1]], f"stream_profile:{self.base}9", client
+                    ))
+                elif op == "reconcile":
+                    key = profile_connections_key(profiles[rest[0]].id)
+                    out.append(reconcile_counter(key, rest[1], rest[2], rest[3], client))
+        return out
+
+    def _keys(self):
+        ids = [self.base + i for i in (1, 2, 3)]
+        keys = []
+        for pid in ids:
+            keys += [profile_connections_key(pid), profile_credential_release_key(pid)]
+        keys += [self.cred_key("a"), self.cred_key("b"), f"stream_profile:{self.base}9"]
+        return keys + [slot_version_key(k) for k in list(keys)]
+
+    def _assert_parity(self, start, steps):
+        names = {"base": self.base, "p1": self.base + 1, "p3": self.base + 3}
+        for key, value in start.items():
+            self.redis.set(key.format(**names), value)
+        fake = _DictRedis()
+        for key, value in start.items():
+            fake.set(key.format(**names), value)
+        real_out = self._run(self.redis, steps)
+        fake_out = self._run(fake, steps)
+        self.assertEqual(fake_out, real_out)
+        for key in self._keys():
+            real_value = self.redis.get(key)
+            self.assertEqual(fake.get(key), real_value, key)
+
+    def test_reserve_release_refusal_and_repair_sequences_agree(self):
+        self._assert_parity(
+            # c is unlimited, so nothing reserves its counter back up from -4:
+            # only a release's repair can move it.
+            {
+                "profile_connections:{p1}": "-2",
+                "profile_connections:{p3}": "-4",
+                "server_group_connections:{base}:b": "-1",
+            },
+            [("reserve", "a"), ("reserve", "a"), ("reserve", "a"), ("reserve", "b"),
+             ("reserve", "b"), ("reserve", "c"), ("release", "a"), ("release", "a"),
+             ("release", "b"), ("release", "c")],
+        )
+
+    def test_switch_and_reconcile_sequences_agree(self):
+        self._assert_parity(
+            {"server_group_connections:{base}:b": "1"},
+            [("reserve", "a"), ("switch", "a", "b"), ("release", "b"), ("switch", "a", "b"),
+             ("switch", "a", "c"), ("reconcile", "a", 3, 0, 0), ("reconcile", "c", 1, 0, 0),
+             ("reconcile", "c", 0, 2, 2)],
+        )
+
+
+# Five profiles: a, b and c share login "x" (so a full shared login refuses a
+# reserve and a switch with credential_full), d has login "y", e is in no
+# group; c is unlimited, so nothing but a release's repair moves its counter.
+_PROFILES = {"a": (1, 2, "x"), "b": (2, 1, "x"), "c": (3, 0, "x"), "d": (4, 1, "y"), "e": (5, 2, None)}
+_NAMES = sorted(_PROFILES)
+_START = st.none() | st.integers(min_value=-3, max_value=3)
+_OPS = st.lists(
+    st.one_of(
+        st.tuples(st.just("reserve"), st.sampled_from(_NAMES)),
+        st.tuples(st.just("release"), st.sampled_from(_NAMES)),
+        st.tuples(st.just("switch"), st.sampled_from(_NAMES), st.sampled_from(_NAMES)),
+    ),
+    max_size=15,
+)
+
+
+class SlotScriptFakeParityProperties(LiveRedisTestCase):
+    """The fake answers as the Lua does for any sequence, checked after every step.
+
+    Every counter test that runs on an in-memory fake exercises
+    slot_script_fake.py, not the Lua. This property is what ties the two
+    together: random reserve/release/switch sequences over a shared login and
+    drifted (negative, absent or full) starting counters, run on the real
+    script and on the fake, with the return and every key compared after
+    each operation.
+    """
+
+    @given(
+        profile_starts=st.fixed_dictionaries({n: _START for n in _NAMES}),
+        cred_starts=st.fixed_dictionaries({"x": _START, "y": _START}),
+        ops=_OPS,
+    )
+    def test_the_fake_matches_the_lua_after_every_step(self, profile_starts, cred_starts, ops):
+        self.base += 100  # a fresh namespace per example; tearDown's patterns still cover it
+        profiles = {
+            n: self.profile(off, cap, login=login) for n, (off, cap, login) in _PROFILES.items()
+        }
+        keys = []
+        for p in profiles.values():
+            keys += [profile_connections_key(p.id), profile_credential_release_key(p.id)]
+        keys += [self.cred_key("x"), self.cred_key("y"), f"stream_profile:{self.base}9"]
+        keys += [slot_version_key(k) for k in list(keys)]
+        fake = _DictRedis()
+        try:
+            for n, value in profile_starts.items():
+                if value is not None:
+                    self.redis.set(profile_connections_key(profiles[n].id), value)
+                    fake.set(profile_connections_key(profiles[n].id), value)
+            for login, value in cred_starts.items():
+                if value is not None:
+                    self.redis.set(self.cred_key(login), value)
+                    fake.set(self.cred_key(login), value)
+            with self.patched_logins():
+                for step, op in enumerate(ops):
+                    results = []
+                    for client in (self.redis, fake):
+                        if op[0] == "reserve":
+                            results.append(reserve_profile_slot(profiles[op[1]], client))
+                        elif op[0] == "release":
+                            results.append(release_profile_slot(profiles[op[1]].id, client))
+                        else:
+                            results.append(switch_profile_slot(
+                                profiles[op[1]], profiles[op[2]], f"stream_profile:{self.base}9", client
+                            ))
+                    self.assertEqual(results[1], results[0], f"step {step} {op}: the fake answered differently")
+                    for key in keys:
+                        self.assertEqual(
+                            fake.get(key), self.redis.get(key),
+                            f"step {step} {op}: {key} differs between the fake and the Lua",
+                        )
+        finally:
+            self.redis.delete(*keys)
diff --git a/apps/proxy/tests/test_next_source_api.py b/apps/proxy/tests/test_next_source_api.py
index 73b4852b..d9ebd948 100644
--- a/apps/proxy/tests/test_next_source_api.py
+++ b/apps/proxy/tests/test_next_source_api.py
@@ -14,11 +14,12 @@ from django.test import TestCase
 from apps.accounts.models import User
 from apps.channels.models import Channel, ChannelStream, Stream
 from apps.m3u.models import M3UAccount, M3UAccountProfile
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
 from apps.proxy.internal_auth import build_internal_request_header, internal_principal_token
 from core.models import StreamProfile, SystemEvent
 
 
-class FakeRelayApiRedis:
+class FakeRelayApiRedis(SlotScriptFakeMixin):
     """Covers channel_stream, stream_profile and profile_connections --
     the same surface FakeControlPlaneRedis covers in
     test_next_source_resolution.py, reused here at the view layer."""
diff --git a/apps/proxy/tests/test_next_source_resolution.py b/apps/proxy/tests/test_next_source_resolution.py
index 94c46d7c..ad2464ac 100644
--- a/apps/proxy/tests/test_next_source_resolution.py
+++ b/apps/proxy/tests/test_next_source_resolution.py
@@ -13,10 +13,11 @@ from django.test import SimpleTestCase, TestCase
 
 from apps.channels.models import Channel, ChannelStream, Stream
 from apps.m3u.models import M3UAccount, M3UAccountProfile
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
 from core.models import StreamProfile
 
 
-class FakeControlPlaneRedis:
+class FakeControlPlaneRedis(SlotScriptFakeMixin):
     """In-memory Redis stand-in covering the keys next_source.py touches:
     channel_stream, stream_profile and profile_connections counters."""
 
diff --git a/apps/proxy/vod_proxy/multi_worker_connection_manager.py b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
index a8ec0ee7..f9f0a648 100644
--- a/apps/proxy/vod_proxy/multi_worker_connection_manager.py
+++ b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
@@ -1553,118 +1553,6 @@ class MultiWorkerVODConnectionManager:
         except Exception as e:
             logger.error(f"Error during Redis-backed connection cleanup: {e}")
 
-    def create_connection(self, content_type: str, content_uuid: str, content_name: str,
-                         client_id: str, client_ip: str, user_agent: str,
-                         m3u_profile: M3UAccountProfile) -> bool:
-        """Create connection tracking in Redis (same as original but for Redis-backed connections)"""
-        if not self.redis_client:
-            logger.error("Redis client not available for VOD connection tracking")
-            return False
-
-        try:
-            # Check profile connection limits
-            profile_connections_key = f"profile_connections:{m3u_profile.id}"
-            current_connections = self.redis_client.get(profile_connections_key)
-            max_connections = getattr(m3u_profile, 'max_connections', 3)  # Default to 3
-
-            if current_connections and int(current_connections) >= max_connections:
-                logger.warning(f"Profile {m3u_profile.name} connection limit exceeded ({current_connections}/{max_connections})")
-                return False
-
-            # Create connection tracking
-            connection_key = f"vod_proxy:connection:{content_type}:{content_uuid}:{client_id}"
-            content_connections_key = f"vod_proxy:content:{content_type}:{content_uuid}:connections"
-
-            # Check if connection already exists
-            if self.redis_client.exists(connection_key):
-                logger.info(f"Connection already exists for {client_id} - {content_type} {content_name}")
-                self.redis_client.hset(connection_key, "last_activity", str(time.time()))
-                return True
-
-            # Connection data
-            connection_data = {
-                "content_type": content_type,
-                "content_uuid": content_uuid,
-                "content_name": content_name,
-                "client_id": client_id,
-                "client_ip": client_ip,
-                "user_agent": user_agent,
-                "m3u_profile_id": m3u_profile.id,
-                "m3u_profile_name": m3u_profile.name,
-                "connected_at": str(time.time()),
-                "last_activity": str(time.time()),
-                "bytes_sent": "0",
-                "position_seconds": "0"
-            }
-
-            # Use pipeline for atomic operations
-            pipe = self.redis_client.pipeline()
-            pipe.hset(connection_key, mapping=connection_data)
-            pipe.expire(connection_key, self.connection_ttl)
-            pipe.incr(profile_connections_key)
-            pipe.sadd(content_connections_key, client_id)
-            pipe.expire(content_connections_key, self.connection_ttl)
-            pipe.execute()
-
-            logger.info(f"Created Redis-backed VOD connection: {client_id} for {content_type} {content_name}")
-            return True
-
-        except Exception as e:
-            logger.error(f"Error creating Redis-backed connection: {e}")
-            return False
-
-    def remove_connection(self, content_type: str, content_uuid: str, client_id: str):
-        """Remove connection tracking from Redis"""
-        if not self.redis_client:
-            return
-
-        try:
-            connection_key = f"vod_proxy:connection:{content_type}:{content_uuid}:{client_id}"
-            content_connections_key = f"vod_proxy:content:{content_type}:{content_uuid}:connections"
-
-            # Get connection data to find profile
-            connection_data = self.redis_client.hgetall(connection_key)
-            if connection_data:
-                # Convert bytes to strings if needed
-                if isinstance(list(connection_data.keys())[0], bytes):
-                    connection_data = {k: v for k, v in connection_data.items()}
-
-                profile_id = connection_data.get('m3u_profile_id')
-                if profile_id:
-                    profile_connections_key = f"profile_connections:{profile_id}"
-                    current_count = int(self.redis_client.get(profile_connections_key) or 0)
-
-                    # Use pipeline for atomic operations
-                    pipe = self.redis_client.pipeline()
-                    pipe.delete(connection_key)
-                    pipe.srem(content_connections_key, client_id)
-                    if current_count > 0:
-                        pipe.decr(profile_connections_key)
-                    pipe.execute()
-
-                    logger.info(f"Removed Redis-backed connection: {client_id}")
-
-        except Exception as e:
-            logger.error(f"Error removing Redis-backed connection: {e}")
-
-    def update_connection_activity(self, content_type: str, content_uuid: str,
-                                 client_id: str, bytes_sent: int):
-        """Update connection activity in Redis"""
-        if not self.redis_client:
-            return
-
-        try:
-            connection_key = f"vod_proxy:connection:{content_type}:{content_uuid}:{client_id}"
-            pipe = self.redis_client.pipeline()
-            pipe.hset(connection_key, mapping={
-                "last_activity": str(time.time()),
-                "bytes_sent": str(bytes_sent)
-            })
-            pipe.expire(connection_key, self.connection_ttl)
-            pipe.execute()
-        except Exception as e:
-            logger.error(f"Error updating connection activity: {e}")
-
     def find_matching_idle_session(self, content_type: str, content_uuid: str,
                                  client_ip: str, client_user_agent: str,
                                  utc_start=None, utc_end=None, offset=None) -> Optional[str]:
diff --git a/apps/proxy/vod_proxy/tests/test_profile_connections.py b/apps/proxy/vod_proxy/tests/test_profile_connections.py
index 99313b00..d78b2b97 100644
--- a/apps/proxy/vod_proxy/tests/test_profile_connections.py
+++ b/apps/proxy/vod_proxy/tests/test_profile_connections.py
@@ -8,9 +8,10 @@ Covers:
 
 from unittest.mock import MagicMock, patch, call
 from django.test import TestCase
+from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin
 
 
-class FakeRedis:
+class FakeRedis(SlotScriptFakeMixin):
     """Minimal in-memory Redis stand-in for counter tests."""
 
     def __init__(self):
diff --git a/dispatcharr/test_discovery.py b/dispatcharr/test_discovery.py
index 3b1fc16e..4e70bc06 100644
--- a/dispatcharr/test_discovery.py
+++ b/dispatcharr/test_discovery.py
@@ -51,6 +51,18 @@ _PATH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
     ("apps/vod/", ("apps.vod", "apps.output")),
     ("apps/hdhr/", ("apps.output", "apps.channels")),
     ("scripts/coverage_live_path", ("apps.proxy", "apps.channels")),
+    # The provider-slot script (#513) is exercised by every surface that
+    # reserves a slot, and those labels' in-memory fakes run it through
+    # slot_script_fake -- so an edit to either must run all of them, not just
+    # the one label whose directory the file sits in.
+    (
+        "apps/m3u/connection_pool",
+        ("apps.m3u", "apps.channels", "apps.proxy", "apps.proxy.vod_proxy", "apps.timeshift"),
+    ),
+    (
+        "apps/m3u/tests/slot_script_fake",
+        ("apps.m3u", "apps.proxy", "apps.proxy.vod_proxy"),
+    ),
 )
 
 
diff --git a/tests/test_ci_test_routing.py b/tests/test_ci_test_routing.py
index 41f02907..37cbd589 100644
--- a/tests/test_ci_test_routing.py
+++ b/tests/test_ci_test_routing.py
@@ -73,6 +73,31 @@ class ChangedPathRoutingTests(SimpleTestCase):
             with self.subTest(path=path):
                 self.assertEqual(self._labels(path), expected)
 
+    def test_slot_script_change_runs_every_label_that_reserves_a_slot(self):
+        """Pins: apps/m3u/connection_pool.py selected apps.m3u.tests alone.
+
+        The provider-slot script it holds (#513) is exercised by channels
+        (Channel.get_stream/release_stream/update_stream_profile), proxy
+        (next-source and release), vod_proxy and timeshift, so prefix matching
+        ran one label of five for an edit that can break all five. The fake
+        that runs the script for in-memory Redis stand-ins,
+        apps/m3u/tests/slot_script_fake.py, is imported by three labels'
+        tests, and an edit to it selected only the label it sits in.
+        """
+        pool = {
+            "apps.m3u.tests",
+            "apps.channels.tests",
+            "apps.proxy.tests",
+            "apps.proxy.vod_proxy.tests",
+            "apps.timeshift.tests",
+        }
+        fake = {"apps.m3u.tests", "apps.proxy.tests", "apps.proxy.vod_proxy.tests"}
+        self.assertLessEqual(pool, self.available)
+        self.assertEqual(self._labels("apps/m3u/connection_pool.py"), pool)
+        self.assertEqual(self._labels("apps/m3u/tests/slot_script_fake.py"), fake)
+        # The alias is by path prefix, so the rest of apps/m3u stays narrow.
+        self.assertEqual(self._labels("apps/m3u/tasks.py"), {"apps.m3u.tests"})
+
     def test_unaliased_app_change_selects_only_its_own_tests(self):
         """Control: no alias means exactly one label, so the fixes stay narrow.
 
```
<!-- appendix-A-end -->

## Appendix B: PR D1-2, against Appendix A applied to the seed

Produced by `git diff 63c1871d c9eab9f9` (9 files, 726 lines). Apply after Appendix A.

<!-- appendix-B-begin -->
```diff
diff --git a/apps/proxy/vod_proxy/held_records.py b/apps/proxy/vod_proxy/held_records.py
new file mode 100644
index 00000000..fdf3a9e9
--- /dev/null
+++ b/apps/proxy/vod_proxy/held_records.py
@@ -0,0 +1,203 @@
+"""Which provider-slot records this process holds, and a positive signal that it is alive (#513).
+
+A VOD session hash (vod_persistent_connection:<session>) and a catch-up pool
+entry (timeshift:pool:<session>) each stand for one open provider connection,
+and each carries the worker that holds it (`worker_id`, hostname-PID). The
+provider-slot reconciler (apps/proxy/slot_reconciler.py) counts such a record
+as a holder only while that worker's liveness key exists -- NOT while the
+record looks recent. Recency is the wrong signal: a paused player stops
+reading, its generator sits suspended at a `yield`, no chunk loop runs, and
+`last_activity` goes stale while the provider connection stays open and still
+occupies the provider's slot (mwcm.py's chunk loop, timeshift/views.py's
+post-yield heartbeat).
+
+So each relay-uwsgi process runs one refresher, off the request path, that
+every REFRESH_INTERVAL_SECONDS:
+
+- sets `vod:worker:<worker_id>` with a WORKER_KEY_TTL_SECONDS expiry, and
+- re-EXPIREs every record this process's generators currently hold, and
+  re-stamps the record's `worker_id` with this process, so a pause longer than
+  the record's own TTL no longer makes a live holder invisible, and a session
+  another worker took over and then lost is claimed back by the one still
+  holding it.
+
+It is one Lua script per iteration, so one round trip however many records.
+
+Under gevent the refresher is a greenlet on the one OS thread the process has
+(threading is monkey-patched). A hub stall longer than WORKER_KEY_TTL_SECONDS
+makes a live worker read as dead; the reconciler drops a holder only after it
+has been absent from two consecutive runs, so a stall must outlast the TTL
+plus a whole run interval before a count moves. A refresher that died would
+be the other failure, so every iteration catches and logs its own exception
+and the loop goes on. The greenlet dies with its process, which is the point:
+the key then lapses on its own and the reconciler reads that worker as gone.
+
+Tests never start the thread: `SLOT_HOLDER_REFRESHER_ENABLED` is False in
+dispatcharr/settings_test.py, and the tests call refresh_once() directly.
+"""
+
+from __future__ import annotations
+
+import logging
+import os
+import socket
+import threading
+import time
+
+from django.conf import settings
+
+logger = logging.getLogger(__name__)
+
+WORKER_KEY_PREFIX = "vod:worker:"
+WORKER_KEY_TTL_SECONDS = 60
+REFRESH_INTERVAL_SECONDS = 10
+
+_REFRESH_SCRIPT = """
+-- held_records_refresh
+-- KEYS[1]: this worker's liveness key; KEYS[2..]: records this worker holds.
+-- ARGV[1]: worker id; ARGV[2]: liveness TTL; then per record a TTL and the
+-- name of a field that must read '1' for the record to be refreshed ('' = none).
+redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
+local refreshed = 0
+for i = 2, #KEYS do
+  local ttl = tonumber(ARGV[2 * i - 1])
+  local busy = ARGV[2 * i]
+  if redis.call('EXISTS', KEYS[i]) == 1 then
+    if busy == '' or redis.call('HGET', KEYS[i], busy) == '1' then
+      redis.call('EXPIRE', KEYS[i], ttl)
+      redis.call('HSET', KEYS[i], 'worker_id', ARGV[1])
+      refreshed = refreshed + 1
+    end
+  end
+end
+return refreshed
+"""
+
+
+def current_worker_id() -> str:
+    """This process's holder id: hostname-PID, what VOD hashes always carried."""
+    try:
+        return f"{socket.gethostname()}-{os.getpid()}"
+    except Exception:
+        return f"worker-{os.getpid()}"
+
+
+def worker_key(worker_id: str) -> str:
+    return f"{WORKER_KEY_PREFIX}{worker_id}"
+
+
+class HeldRecords:
+    """The records one process's streaming generators hold, and their refresher."""
+
+    def __init__(self, redis_client=None, worker_id=None):
+        self._redis_client = redis_client
+        self._worker_id = worker_id
+        self._held = {}
+        self._lock = threading.Lock()
+        self._started = False
+        self._failing = False
+
+    @property
+    def worker_id(self) -> str:
+        return self._worker_id or current_worker_id()
+
+    def _client(self):
+        if self._redis_client is None:
+            from core.utils import RedisClient
+
+            self._redis_client = RedisClient.get_client()
+        return self._redis_client
+
+    def hold(self, key: str, *, ttl: int, busy_field: str = "") -> object:
+        """Register `key` as held by this process until release(token)."""
+        token = object()
+        with self._lock:
+            self._held[token] = (key, int(ttl), busy_field)
+        self._ensure_started()
+        return token
+
+    def release(self, token) -> None:
+        with self._lock:
+            self._held.pop(token, None)
+
+    def held_keys(self):
+        with self._lock:
+            return sorted({key for key, _ttl, _busy in self._held.values()})
+
+    def held_entries(self):
+        """Every (key, ttl, busy_field) held, as the refresher will refresh it."""
+        with self._lock:
+            return sorted(set(self._held.values()))
+
+    def holding(self, key: str, iterable, *, ttl: int, busy_field: str = ""):
+        """Yield from `iterable`, holding `key` from the first item until it ends or closes.
+
+        A generator, so nothing is registered for a response that is never
+        iterated; `yield from` hands close() and exceptions to the wrapped
+        generator exactly as a direct close would.
+        """
+        token = self.hold(key, ttl=ttl, busy_field=busy_field)
+        try:
+            yield from iterable
+        finally:
+            self.release(token)
+
+    def refresh_once(self) -> int:
+        """One refresher iteration. Never raises; returns records refreshed, or -1."""
+        try:
+            with self._lock:
+                records = list(self._held.values())
+            by_key = {}
+            for key, ttl, busy in records:
+                previous = by_key.get(key)
+                by_key[key] = (max(ttl, previous[0]) if previous else ttl, busy)
+            keys = [worker_key(self.worker_id)] + list(by_key)
+            args = [self.worker_id, WORKER_KEY_TTL_SECONDS]
+            for ttl, busy in by_key.values():
+                args += [ttl, busy]
+            client = self._client()
+            refreshed = int(client.register_script(_REFRESH_SCRIPT)(keys=keys, args=args))
+            if self._failing:
+                logger.info("Slot-holder refresher for %s recovered", self.worker_id)
+                self._failing = False
+            return refreshed
+        except Exception as exc:
+            if not self._failing:
+                logger.warning(
+                    "Slot-holder refresher for %s failed; retrying every %ss: %s",
+                    self.worker_id, REFRESH_INTERVAL_SECONDS, type(exc).__name__,
+                )
+                self._failing = True
+            return -1
+
+    def _run(self) -> None:
+        while True:
+            try:
+                self.refresh_once()
+            except Exception:  # refresh_once already catches; belt and braces
+                logger.exception("Slot-holder refresher iteration raised")
+            time.sleep(REFRESH_INTERVAL_SECONDS)
+
+    def _ensure_started(self) -> None:
+        if self._started or not getattr(settings, "SLOT_HOLDER_REFRESHER_ENABLED", True):
+            return
+        with self._lock:
+            if self._started:
+                return
+            self._started = True
+        thread = threading.Thread(target=self._run, name="slot-holder-refresher", daemon=True)
+        thread.start()
+
+
+_process_records = None
+_process_lock = threading.Lock()
+
+
+def this_process() -> HeldRecords:
+    """The one HeldRecords of this process, shared by VOD and catch-up."""
+    global _process_records
+    if _process_records is None:
+        with _process_lock:
+            if _process_records is None:
+                _process_records = HeldRecords()
+    return _process_records
diff --git a/apps/proxy/vod_proxy/multi_worker_connection_manager.py b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
index f9f0a648..f9eed6db 100644
--- a/apps/proxy/vod_proxy/multi_worker_connection_manager.py
+++ b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
@@ -13,6 +13,7 @@ from urllib.parse import urlparse
 from typing import Optional, Dict, Any
 from django.http import StreamingHttpResponse, HttpResponse
 from core.utils import RedisClient
+from apps.proxy.vod_proxy import held_records
 from apps.proxy.vod_proxy.byte_range import (
     UNSATISFIABLE,
     parse_length,
@@ -92,6 +93,10 @@ end
 return 1
 """
 
+# The session hash's TTL, refreshed on every metadata save and, while a
+# generator holds the session, by this process's slot-holder refresher (#513).
+SESSION_TTL_SECONDS = 3600
+
 # Cache register_script handles per redis client (EVALSHA thereafter).
 _vod_script_cache: Dict[int, Dict[str, Any]] = {}
 
@@ -338,11 +343,11 @@ class RedisBackedVODConnection:
             if include_active_streams:
                 # Session creation: key may not exist yet.
                 self.redis_client.hset(self.connection_key, mapping=data)
-                self.redis_client.expire(self.connection_key, 3600)
+                self.redis_client.expire(self.connection_key, SESSION_TTL_SECONDS)
                 return True
 
             # Flat field/value list for Lua: TTL, then pairs
-            args = ['3600']
+            args = [str(SESSION_TTL_SECONDS)]
             for field, value in data.items():
                 args.extend([str(field), str(value)])
 
@@ -813,15 +818,13 @@ class MultiWorkerVODConnectionManager:
         logger.info(f"MultiWorkerVODConnectionManager initialized for worker {self.worker_id}")
 
     def _get_worker_id(self):
-        """Get unique worker ID for this process"""
-        import os
-        import socket
-        try:
-            # Use combination of hostname and PID for unique worker ID
-            return f"{socket.gethostname()}-{os.getpid()}"
-        except:
-            import random
-            return f"worker-{random.randint(1000, 9999)}"
+        """Get unique worker ID for this process (hostname-PID).
+
+        held_records owns the formula since #513: a catch-up pool entry
+        records the same id, and the provider-slot reconciler reads both
+        against the one liveness key per process.
+        """
+        return held_records.current_worker_id()
 
     def _get_profile_connections_key(self, profile_id: int) -> str:
         """Get Redis key for tracking connections per profile - STANDARDIZED with TS proxy"""
@@ -1309,8 +1312,16 @@ class MultiWorkerVODConnectionManager:
                             cleanup_thread.start()
 
             # Create streaming response
+            # Held from the first chunk until the generator ends or closes, so
+            # this process's refresher keeps the session hash alive and owned
+            # through a pause of any length (#513): a paused player's
+            # generator sits at a yield and the chunk loop never refreshes it.
             response = StreamingHttpResponse(
-                streaming_content=stream_generator(),
+                streaming_content=held_records.this_process().holding(
+                    redis_connection.connection_key,
+                    stream_generator(),
+                    ttl=SESSION_TTL_SECONDS,
+                ),
                 content_type=connection_headers.get('content_type', 'video/mp4')
             )
 
diff --git a/apps/proxy/vod_proxy/tests/test_held_records.py b/apps/proxy/vod_proxy/tests/test_held_records.py
new file mode 100644
index 00000000..f7f313d5
--- /dev/null
+++ b/apps/proxy/vod_proxy/tests/test_held_records.py
@@ -0,0 +1,226 @@
+"""The slot-holder registry and refresher (#513 constraints 4 and 5).
+
+A VOD session hash or a busy catch-up pool entry counts toward the provider
+slot only while the worker holding it is alive, and "alive" is a key the
+worker's own refresher keeps setting -- never the record's recency, which a
+paused player lets go stale while its provider connection stays open. These
+run against the live Redis the suite already uses; without it they skip,
+except under CI, where they fail.
+"""
+
+from __future__ import annotations
+
+import os
+import threading
+import uuid
+from unittest import mock
+
+from django.test import SimpleTestCase, override_settings
+
+from apps.proxy.vod_proxy import held_records
+from apps.proxy.vod_proxy.held_records import (
+    REFRESH_INTERVAL_SECONDS,
+    WORKER_KEY_TTL_SECONDS,
+    HeldRecords,
+    worker_key,
+)
+
+
+def _live_redis():
+    from core.utils import RedisClient
+
+    try:
+        client = RedisClient.get_client(max_retries=1, retry_interval=0)
+        if client is not None and client.ping():
+            return client
+    except Exception:
+        pass
+    return None
+
+
+class HeldRecordsRealRedisTests(SimpleTestCase):
+    redis = None
+
+    @classmethod
+    def setUpClass(cls):
+        super().setUpClass()
+        cls.redis = _live_redis()
+
+    def setUp(self):
+        if self.redis is None:
+            if os.environ.get("CI"):
+                self.fail("Redis is not reachable under CI: these tests must run, not skip")
+            self.skipTest("Redis not available")
+        tag = uuid.uuid4().hex[:12]
+        self.worker = f"test-host-{tag}"
+        self.vod_key = f"vod_persistent_connection:held-{tag}"
+        self.pool_key = f"timeshift:pool:held-{tag}"
+        self.records = HeldRecords(self.redis, self.worker)
+
+    def tearDown(self):
+        if self.redis is not None:
+            self.redis.delete(self.vod_key, self.pool_key, worker_key(self.worker))
+
+    def test_refresh_sets_the_worker_liveness_key_with_a_short_ttl(self):
+        self.assertEqual(self.records.refresh_once(), 0)
+        self.assertEqual(self.redis.get(worker_key(self.worker)), self.worker)
+        ttl = self.redis.ttl(worker_key(self.worker))
+        self.assertTrue(0 < ttl <= WORKER_KEY_TTL_SECONDS, ttl)
+        # Several refresh periods fit inside one TTL, so one missed beat is not a death.
+        self.assertGreaterEqual(WORKER_KEY_TTL_SECONDS, 3 * REFRESH_INTERVAL_SECONDS)
+
+    def test_a_held_vod_session_outlives_its_own_ttl_while_held(self):
+        # The paused viewer: the hash is about to expire and nothing in the
+        # chunk loop will refresh it, because the loop is not running.
+        self.redis.hset(self.vod_key, mapping={"active_streams": "1", "worker_id": "someone-else"})
+        self.redis.expire(self.vod_key, 5)
+        token = self.records.hold(self.vod_key, ttl=3600)
+        self.assertEqual(self.records.refresh_once(), 1)
+        self.assertGreater(self.redis.ttl(self.vod_key), 3000)
+        # ...and the record now names the worker that actually holds it.
+        self.assertEqual(self.redis.hget(self.vod_key, "worker_id"), self.worker)
+        self.records.release(token)
+        self.redis.expire(self.vod_key, 5)
+        self.assertEqual(self.records.refresh_once(), 0)
+        self.assertLessEqual(self.redis.ttl(self.vod_key), 5)
+
+    def test_a_catch_up_entry_is_refreshed_only_while_busy(self):
+        self.redis.hset(self.pool_key, mapping={"busy": "1", "profile_id": "7"})
+        self.redis.expire(self.pool_key, 5)
+        self.records.hold(self.pool_key, ttl=600, busy_field="busy")
+        self.assertEqual(self.records.refresh_once(), 1)
+        self.assertGreater(self.redis.ttl(self.pool_key), 500)
+        # Released to idle (busy=0, the 60 s idle TTL): the refresher must not
+        # stretch an idle entry back to the busy TTL.
+        self.redis.hset(self.pool_key, "busy", "0")
+        self.redis.expire(self.pool_key, 60)
+        self.assertEqual(
+            self.records.refresh_once(), 0,
+            "an idle catch-up entry was refreshed to the busy TTL",
+        )
+        self.assertLessEqual(self.redis.ttl(self.pool_key), 60)
+
+    def test_a_record_already_gone_is_not_recreated(self):
+        self.records.hold(self.vod_key, ttl=3600)
+        self.assertEqual(self.records.refresh_once(), 0)
+        self.assertEqual(self.redis.exists(self.vod_key), 0)
+
+    def test_holding_registers_from_the_first_item_until_the_end_or_close(self):
+        def gen():
+            yield b"a"
+            yield b"b"
+
+        wrapped = self.records.holding(self.vod_key, gen(), ttl=3600)
+        self.assertEqual(self.records.held_keys(), [])  # nothing until iterated
+        self.assertEqual(next(wrapped), b"a")
+        self.assertEqual(self.records.held_keys(), [self.vod_key])
+        self.assertEqual(list(wrapped), [b"b"])
+        self.assertEqual(self.records.held_keys(), [])
+
+        closed = []
+
+        def gen2():
+            try:
+                yield b"a"
+                yield b"b"
+            finally:
+                closed.append(True)
+
+        wrapped = self.records.holding(self.vod_key, gen2(), ttl=3600)
+        next(wrapped)
+        wrapped.close()
+        self.assertEqual(closed, [True], "close() did not reach the wrapped generator")
+        self.assertEqual(self.records.held_keys(), [])
+
+
+class HeldRecordsLoopTests(SimpleTestCase):
+    """The refresher never dies of an exception and starts only when enabled."""
+
+    def test_refresh_once_swallows_a_redis_failure_and_logs_once(self):
+        broken = mock.MagicMock()
+        broken.register_script.side_effect = ConnectionError("redis went away")
+        records = HeldRecords(broken, "w1")
+        with self.assertLogs(held_records.logger, "WARNING") as logs:
+            self.assertEqual(records.refresh_once(), -1)
+            self.assertEqual(records.refresh_once(), -1)
+        self.assertEqual(len(logs.records), 1, "a failure streak should log once, not every beat")
+
+    def test_the_loop_keeps_going_after_an_iteration_raises(self):
+        records = HeldRecords(mock.MagicMock(), "w1")
+        calls = []
+
+        class Stop(BaseException):
+            pass
+
+        def refresh():
+            calls.append(1)
+            if len(calls) == 1:
+                raise RuntimeError("an iteration blew up")
+            return 0
+
+        def sleep(_seconds):
+            if len(calls) >= 3:
+                raise Stop
+
+        with mock.patch.object(records, "refresh_once", side_effect=refresh), \
+                mock.patch.object(held_records.time, "sleep", side_effect=sleep), \
+                self.assertLogs(held_records.logger, "ERROR"):
+            with self.assertRaises(Stop):
+                records._run()
+        self.assertEqual(len(calls), 3, "the refresher stopped after an iteration raised")
+
+    @override_settings(SLOT_HOLDER_REFRESHER_ENABLED=True)
+    def test_the_first_hold_starts_one_refresher_thread(self):
+        records = HeldRecords(mock.MagicMock(), "w1")
+        with mock.patch.object(held_records.threading, "Thread") as thread:
+            records.hold("k1", ttl=10)
+            records.hold("k2", ttl=10)
+        thread.assert_called_once()
+        self.assertEqual(thread.call_args.kwargs["name"], "slot-holder-refresher")
+        self.assertTrue(thread.call_args.kwargs["daemon"])
+        thread.return_value.start.assert_called_once_with()
+
+    def test_no_refresher_thread_in_tests(self):
+        records = HeldRecords(mock.MagicMock(), "w1")
+        with mock.patch.object(held_records.threading, "Thread") as thread:
+            records.hold("k1", ttl=10)
+        thread.assert_not_called()
+
+    def test_this_process_is_one_registry_shared_by_every_caller(self):
+        self.assertIs(held_records.this_process(), held_records.this_process())
+
+    def test_the_vod_manager_and_catch_up_record_the_same_worker_id(self):
+        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
+            MultiWorkerVODConnectionManager,
+        )
+
+        manager = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
+        self.assertEqual(manager._get_worker_id(), held_records.current_worker_id())
+        self.assertEqual(held_records.current_worker_id(), f"{__import__('socket').gethostname()}-{os.getpid()}")
+
+
+class VodStreamHoldsItsSessionTests(SimpleTestCase):
+    """stream_content_with_session's response holds the session hash while it streams."""
+
+    def test_the_session_is_held_from_the_first_chunk_until_the_stream_ends(self):
+        from apps.proxy.vod_proxy.tests.test_vod_range_responses import VodRangeResponseTests
+
+        case = VodRangeResponseTests("test_a_provider_416_on_a_first_request_was_a_500")
+        case.setUp()
+        try:
+            response = case._get(None)
+            self.assertEqual(response.status_code, 200)
+            key = f"vod_persistent_connection:{case.SESSION}"
+            registry = held_records.this_process()
+            self.assertNotIn(key, registry.held_keys())
+            chunks = iter(response.streaming_content)
+            next(chunks)
+            self.assertIn(key, registry.held_keys(), "a streaming VOD response did not hold its session")
+            self.assertIn(
+                (key, 3600, ""), registry.held_entries(),
+                "a streaming VOD response held its session with the wrong TTL or a busy guard",
+            )
+            list(chunks)
+            self.assertNotIn(key, registry.held_keys())
+        finally:
+            case.doCleanups()
diff --git a/apps/timeshift/tests/test_pool_worker_id.py b/apps/timeshift/tests/test_pool_worker_id.py
new file mode 100644
index 00000000..35f3185a
--- /dev/null
+++ b/apps/timeshift/tests/test_pool_worker_id.py
@@ -0,0 +1,74 @@
+"""A busy catch-up pool entry names the process holding it (#513 constraint 5).
+
+The provider-slot reconciler counts a busy entry only while its worker's
+liveness key exists, so the entry must say which worker that is -- at
+creation, and again when an idle entry is taken back into use -- and a
+streaming response must hold the entry for its whole life.
+"""
+
+from unittest.mock import MagicMock, patch
+
+from django.test import TestCase
+
+from apps.proxy.vod_proxy import held_records
+from apps.timeshift import views
+from apps.timeshift.redis_keys import TimeshiftRedisKeys
+from apps.timeshift.tests.test_views import (
+    _FakeRedis,
+    _fake_upstream,
+    _seed_pool_session,
+)
+
+
+class PoolEntryWorkerIdTests(TestCase):
+    def test_a_created_entry_records_this_process(self):
+        redis = _FakeRedis()
+        _seed_pool_session(redis, session_id="s1")
+        self.assertEqual(
+            redis.hget(TimeshiftRedisKeys.pool("s1"), "worker_id"),
+            held_records.current_worker_id(),
+        )
+
+    def test_an_idle_entry_taken_back_records_the_process_taking_it(self):
+        redis = _FakeRedis()
+        _seed_pool_session(redis, session_id="s1", busy="0")
+        redis.hset(TimeshiftRedisKeys.pool("s1"), "worker_id", "host-that-died-1")
+        profile = MagicMock(id=31)
+        with patch.object(views.M3UAccountProfile.objects, "get", return_value=profile), \
+                patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)):
+            acquired = views._acquire_idle_pool_session(redis, "s1")
+        self.assertIsNotNone(acquired)
+        self.assertEqual(
+            redis.hget(TimeshiftRedisKeys.pool("s1"), "worker_id"),
+            held_records.current_worker_id(),
+        )
+
+
+class CatchupStreamHoldsItsPoolEntryTests(TestCase):
+    def test_the_pool_entry_is_held_from_the_first_chunk_until_close(self):
+        # Imported here, not at module level: a TestCase class in this
+        # module's namespace would be collected and run a second time.
+        from apps.timeshift.tests.test_views import StreamFromProviderStatusMappingTests
+
+        fixture = StreamFromProviderStatusMappingTests("test_all_candidates_404_returns_404")
+        fixture.setUp()
+        kwargs = dict(fixture.kwargs, pool_session_id="pool-s1")
+        upstream = _fake_upstream(200)
+        key = TimeshiftRedisKeys.pool("pool-s1")
+        registry = held_records.this_process()
+        with patch.object(views, "_open_upstream", return_value=upstream), \
+                patch.object(views, "_iter_upstream_with_stop", return_value=iter([b"a", b"b"])), \
+                patch.object(views, "RedisClient"), \
+                patch.object(views, "_register_stats_client"), \
+                patch.object(views, "_unregister_stats_client"):
+            response = views._stream_from_provider(**kwargs)
+            self.assertEqual(response.status_code, 200)
+            chunks = iter(response.streaming_content)
+            next(chunks)
+            self.assertIn(key, registry.held_keys(), "a streaming catch-up response did not hold its pool entry")
+            self.assertIn(
+                (key, 600, "busy"), registry.held_entries(),
+                "a streaming catch-up response held its pool entry without the busy guard or the busy TTL",
+            )
+            response.close()
+        self.assertNotIn(key, registry.held_keys())
diff --git a/apps/timeshift/views.py b/apps/timeshift/views.py
index a9255c64..024e8f9c 100644
--- a/apps/timeshift/views.py
+++ b/apps/timeshift/views.py
@@ -39,6 +39,8 @@ from apps.m3u.models import M3UAccount, M3UAccountProfile
 from apps.m3u.tasks import get_transformed_credentials
 from apps.proxy.config_helper import ConfigHelper
 from apps.proxy.constants import ChannelMetadataField, ChannelState
+from apps.proxy.vod_proxy import held_records
+from apps.proxy.vod_proxy.held_records import current_worker_id
 from apps.timeshift.redis_keys import (
     TimeshiftRedisKeys,
     mint_session_id,
@@ -2170,6 +2172,7 @@ def _acquire_idle_pool_session(
             redis_client.hset(key, mapping={
                 "busy": "1",
                 "last_activity": str(time.time()),
+                "worker_id": current_worker_id(),
             })
             redis_client.expire(key, _POOL_ENTRY_TTL)
             return dict(data), profile
@@ -2235,6 +2238,10 @@ def _create_pool_session(
                 "provider_tz_name": str(provider_tz_name or ""),
                 "busy": "1",
                 "last_activity": now,
+                # The process holding the provider connection: the slot
+                # reconciler counts a busy entry only while this worker's
+                # liveness key exists (#513).
+                "worker_id": current_worker_id(),
             })
             redis_client.expire(key, _POOL_ENTRY_TTL)
         try:
@@ -3640,7 +3647,19 @@ def _stream_from_provider(
     def _finish_session_backup():
         _finish_session(close_upstream=True)
 
-    stream_iter = _SlotReleasingStream(stream_generator(), _finish_session_backup)
+    # Held from the first chunk until the generator ends or closes: this
+    # process's refresher keeps the busy pool entry alive and owned through a
+    # pause longer than _POOL_ENTRY_TTL, which the post-yield heartbeat above
+    # cannot do while the player is not reading (#513).
+    stream_iter = _SlotReleasingStream(
+        held_records.this_process().holding(
+            _pool_key(pool_session_id or client_id),
+            stream_generator(),
+            ttl=_POOL_ENTRY_TTL,
+            busy_field="busy",
+        ),
+        _finish_session_backup,
+    )
     response = StreamingHttpResponse(
         stream_iter,
         content_type=content_type,
diff --git a/dispatcharr/settings.py b/dispatcharr/settings.py
index b317963d..5f833556 100644
--- a/dispatcharr/settings.py
+++ b/dispatcharr/settings.py
@@ -435,6 +435,11 @@ CELERY_TASK_SERIALIZER = "json"
 # Prevents unbounded growth from memory fragmentation or unexpected leaks.
 CELERY_WORKER_MAX_MEMORY_PER_CHILD = 524_288  # 512 MB in KB
 
+# Each relay-uwsgi process refreshes a liveness key for the provider-slot
+# reconciler and re-EXPIREs the VOD/catch-up records its streams hold
+# (apps/proxy/vod_proxy/held_records.py, #513). Off only in tests.
+SLOT_HOLDER_REFRESHER_ENABLED = True
+
 CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers.DatabaseScheduler"
 CELERY_BEAT_SCHEDULE = {
     # Keep the file scanning task
diff --git a/dispatcharr/settings_test.py b/dispatcharr/settings_test.py
index e2d346f8..e7d05b32 100644
--- a/dispatcharr/settings_test.py
+++ b/dispatcharr/settings_test.py
@@ -32,6 +32,10 @@ PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
 CELERY_TASK_ALWAYS_EAGER = False
 CELERY_TASK_EAGER_PROPAGATES = False
 
+# No background slot-holder refresher thread in tests: its tests call
+# HeldRecords.refresh_once() directly (apps/proxy/vod_proxy/held_records.py).
+SLOT_HOLDER_REFRESHER_ENABLED = False
+
 _use_sqlite = os.environ.get("TEST_USE_SQLITE", "").lower() in ("1", "true", "yes")
 
 if _use_sqlite:
diff --git a/dispatcharr/test_discovery.py b/dispatcharr/test_discovery.py
index 4e70bc06..f0f41288 100644
--- a/dispatcharr/test_discovery.py
+++ b/dispatcharr/test_discovery.py
@@ -63,6 +63,12 @@ _PATH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
         "apps/m3u/tests/slot_script_fake",
         ("apps.m3u", "apps.proxy", "apps.proxy.vod_proxy"),
     ),
+    # The slot-holder registry (#513) is imported by VOD, by catch-up and by
+    # the provider-slot reconciler's tests.
+    (
+        "apps/proxy/vod_proxy/held_records",
+        ("apps.proxy.vod_proxy", "apps.proxy", "apps.timeshift"),
+    ),
 )
 
 
diff --git a/tests/test_ci_test_routing.py b/tests/test_ci_test_routing.py
index 37cbd589..ad43c21e 100644
--- a/tests/test_ci_test_routing.py
+++ b/tests/test_ci_test_routing.py
@@ -98,6 +98,21 @@ class ChangedPathRoutingTests(SimpleTestCase):
         # The alias is by path prefix, so the rest of apps/m3u stays narrow.
         self.assertEqual(self._labels("apps/m3u/tasks.py"), {"apps.m3u.tests"})
 
+    def test_held_records_change_runs_every_label_that_holds_or_reads_a_record(self):
+        """Pins: apps/proxy/vod_proxy/held_records.py selected apps.proxy.vod_proxy.tests alone.
+
+        Catch-up (apps.timeshift.tests) holds its pool entries through it, and
+        the provider-slot reconciler's tests (apps.proxy.tests) read its
+        liveness keys, so an edit to it can break either label (#513).
+        """
+        expected = {"apps.proxy.vod_proxy.tests", "apps.proxy.tests", "apps.timeshift.tests"}
+        self.assertLessEqual(expected, self.available)
+        self.assertEqual(self._labels("apps/proxy/vod_proxy/held_records.py"), expected)
+        # The rest of vod_proxy stays narrow.
+        self.assertEqual(
+            self._labels("apps/proxy/vod_proxy/views.py"), {"apps.proxy.vod_proxy.tests"}
+        )
+
     def test_unaliased_app_change_selects_only_its_own_tests(self):
         """Control: no alias means exactly one label, so the fixes stay narrow.
 
```
<!-- appendix-B-end -->

## Appendix C: PR D1-3, against Appendices A and B applied to the seed

Produced by `git diff c9eab9f9 c85ec38a` (9 files, 1,086 lines). Apply after Appendices A and B.

<!-- appendix-C-begin -->
```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 69e27db9..256617d3 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -128,7 +128,7 @@ Correctness:
 - **A buffering timeout with no alternate no longer asks `next-source` on every progress record** ([#302](https://github.com/D10Scot/Dispatcharr/issues/302), fixed in #394): a failed switch defers the next ask by one `buffering_timeout`.
 - **An fMP4 viewer is no longer dropped 40s into a stall a TS viewer survives** ([#222](https://github.com/D10Scot/Dispatcharr/issues/222), fixed in #400, row 12): `serveFMP4Client` now leaves by the TS loop's exit, never on a healthy channel and after `MAX_KEEPALIVE_DURATION` on an unhealthy one, with no keepalive bytes written.
 - **`channel_stream:*`/`stream_profile:*` had two independent owners before Phase 1 PR 6**: both keys were read *and written* by `apps/channels/models.py` and independently by `apps/proxy/live_proxy/`, with neither key in `RedisKeys`. As of PR 6 they are `RedisKeys.channel_stream` / `RedisKeys.stream_profile`, and Django is the only writer — `apps/channels/models.py` (`get_stream`/`release_stream`/`update_stream_profile`/`_release_stale_stream_assignment`) plus the channel-deleted fallback in `apps/proxy/next_source.py`'s `release_source()`, which runs in the API process, never in the relay — the relay reaches them only through `POST /api/relay/channels/<identifier>/next-source` and `/release`. The Python relay read them directly (`live_proxy/views.py`) on purpose — they are Django-owned keys, not relay state, so PR 7's "no control-plane code reads relay keys" never covered them — and stage 2d-4 deleted that reader. **Django is now the only process that touches either key at all**, which is the shape PR 6 was aiming at and did not reach: the Go relay learns the stream and profile from the `next-source` answer and never opens Redis.
-- **Every write to a provider-slot counter goes through one Lua script** (#513). `apps/m3u/connection_pool.py`'s `_SLOT_SCRIPT` reserves, releases, switches and reconciles `profile_connections:{id}` and `server_group_connections:{group}:{fp}`, and every write bumps `slot_version:<counter key>` in the same step. A direct `INCR`/`DECR`/`SET` on either family anywhere else moves a counter without moving its version, which is the one change the provider-slot reconciler cannot see; `Channel.update_stream_profile()`'s own pipeline was such a writer until #513. The script also makes both negative-counter repairs atomic (#470 on the credential counter, #471 on the profile counter) and checks both caps before writing either, so a refused reserve writes nothing where it used to `INCR` then `DECR`. In-memory test fakes run it through `apps/m3u/tests/slot_script_fake.py`, which `apps/m3u/tests/test_slot_script.py`'s `SlotScriptFakeParityTests` holds to the Lua on a live Redis.
+- **Every write to a provider-slot counter goes through one Lua script** (#513). `apps/m3u/connection_pool.py`'s `_SLOT_SCRIPT` reserves, releases, switches and reconciles `profile_connections:{id}` and `server_group_connections:{group}:{fp}`, and every write bumps `slot_version:<counter key>` in the same step. A direct `INCR`/`DECR`/`SET` on either family anywhere else moves a counter without moving its version, which is the one change the provider-slot reconciler cannot see; `Channel.update_stream_profile()`'s own pipeline was such a writer until #513. The script also makes both negative-counter repairs atomic (#470 on the credential counter, #471 on the profile counter) and checks both caps before writing either, so a refused reserve writes nothing where it used to `INCR` then `DECR`. In-memory test fakes run it through `apps/m3u/tests/slot_script_fake.py`, which `apps/m3u/tests/test_slot_script.py`'s `SlotScriptFakeParityTests` holds to the Lua on a live Redis. The counters are also reconciled: a beat task on the worker role (`apps/proxy/slot_reconciler.py`, ticking every 30 s against a derived minimum spacing of about 80 s) recomputes both families from the relay's channel list and the VOD and catch-up records whose worker is alive (`vod:worker:<worker_id>`, kept alive by `apps/proxy/vod_proxy/held_records.py`'s refresher), writes only where a counter's version has not moved since its previous run, and skips the run when the relay cannot answer. A leaked slot is released two runs after its holder was last seen, but only on a counter that has also had one quiet run interval (about 90 s at defaults) with no reserve, release or switch: under sustained churn the correction waits for the churn to stop, because the version rule refuses to write across any writer.
 - **#190 is closed by deletion.** Stage 2d-4 removed all five of its ranges from `apps/channels/models.py` — three reads and two `hdel`s against `live:channel:<uuid>:metadata`, a key the Go relay never writes, so every read had returned `None` and every `hdel` had been a no-op since the 2d-3 cutover. What it described, for the record: **a control-plane write to the relay metadata hash on every successful `Channel.release_stream()`, plus THREE fallback-path reads** — `release_stream()`'s recovery branch, a second fallback read in the same method that CLAUDE.md never recorded, and `_release_stale_stream_assignment()`, which `get_stream()` calls and `release_stream()` does not ([#190](https://github.com/D10Scot/Dispatcharr/issues/190)). The `hdel` ran on **every** successful release, not only in a rare recovery branch, clearing `ChannelMetadataField.STREAM_ID`/`M3U_PROFILE` so a duplicate release could not `DECR` the provider counter twice — which is why the writes were never as easy as the reads and why this waited for the deletion rather than being fixed in place. Everything else — the reuse check, the DVR client scans, `fetch_channel_stats`, the recording metadata capture and the live branch of `get_user_active_connections` — goes through `apps/proxy/relay_client.py`.
 - **`get_user_active_connections` has five callers** — four more than the bullet said for most of its life, the fifth being `check_user_stream_limits` at `apps/proxy/utils.py:354`, which takes the `include_live=True` default and is the other live one. **One of them used to trigger a relay side effect on every call.** Three timeshift helpers (`_session_has_active_timeshift_stream`, `_preempt_playback_streams`, `_terminate_previous_timeshift_sessions`) pass `include_live=False` (`apps/proxy/utils.py`), added by a whole-branch-review fix after one of them — reached from `_serve_catchup`, a relay-served view — was making the relay call itself over HTTP per catch-up tune for a live client list it always discarded. The fourth caller, `apps/output/views.py`'s `xc_get_info` (the Xtream `player_api.php` handshake, every XC session), is deliberately left asking for the live count — `active_cons` needs it — so that call still reaches `GET /proxy/relay/channels?clients=all` on every handshake, and `get_basic_channel_info` there runs `ClientManager.remove_ghost_clients`, an `SREM` write across every running channel that the old direct Redis scan never performed. **That side effect is gone**, not fixed: the Go relay's client registry is a map in process memory (Phase 2 stage 2c-3), where a client entry cannot outlive the goroutine that made it, so `GET /proxy/relay/channels?clients=all` performs no write at all. `xc_get_info` still makes the call and still gets its `active_cons`; only the `SREM` across every running channel disappeared, at stage 2d-3's flip.
 - **The UDP user-agent filter no longer leaves dangling flags** ([#296](https://github.com/D10Scot/Dispatcharr/issues/296), fixed in #396): a dropped value takes the flag before it and a dropped flag the value after it, which also repairs the shipped Streamlink profile on a UDP upstream.
diff --git a/apps/proxy/slot_reconciler.py b/apps/proxy/slot_reconciler.py
new file mode 100644
index 00000000..eb11a42d
--- /dev/null
+++ b/apps/proxy/slot_reconciler.py
@@ -0,0 +1,404 @@
+"""Recompute the provider-slot counters from ground truth (#513).
+
+`profile_connections:{id}` and `server_group_connections:{group}:{fp}` carry
+no TTL, no owner lease and, until this module, no reconciliation. They drift
+both ways: over-count when a holder dies without releasing (a relay-go crash,
+a release POST lost while the API restarts, a relay-uwsgi crash with VOD
+sessions open, an abandoned catch-up session) and under-count when a counter
+is written down under a live holder (#470, #471, a Redis restart). This
+module periodically derives each counter from who actually holds a provider
+connection and moves the counter toward that, under rules that keep it from
+ever dropping a slot a live holder owns.
+
+Ground truth, per counter:
+
+- live: every channel the relay lists, attributed to the `m3u_profile_id` it
+  reports (`GET /proxy/relay/channels`), except a channel whose run has
+  already ended (`stopped`/`error`: its slot is released or being released);
+- VOD: every `vod_persistent_connection:*` hash with `active_streams > 0`
+  whose worker's liveness key exists, plus a seeded-never-started hash
+  (`active_streams == 0`) while `now - created_at` is inside the VOD
+  in-flight window (#513 constraint 6);
+- catch-up: every `timeshift:pool:*` entry with `busy == "1"` whose worker's
+  liveness key exists.
+
+Records are selected by Redis type (a hash), never by the shape of the key:
+both session ids reach the key verbatim from the client (VOD's
+`<str:session_id>` path segment, catch-up's `?session_id=`), so a `:` in one
+must not hide a live holder. A credential counter's holders are the holders
+of every profile whose release pointer (`profile_credential_release:{id}`,
+what that profile's last reserve or switch actually counted against) names
+it, or, where no pointer exists, whose configuration names it today -- so an
+admin making a pooled profile unlimited, moving it or deleting it mid-stream
+does not lower the shared counter under the streams still open.
+
+A VOD or catch-up record's worker is alive while `vod:worker:<worker_id>`
+exists (apps/proxy/vod_proxy/held_records.py). Recency is never the signal.
+
+The write rule, per counter K, at run N+1 against the snapshot run N saved:
+
+1. K's version (slot_version:K) must be unchanged since run N read it, and
+   the check is made by the slot script at write time, atomically with the
+   write (connection_pool.reconcile_counter). Every writer bumps the version,
+   so "unchanged" means nobody reserved, released or switched on K since run
+   N -- and runs are spaced wider than the longest in-flight window on any
+   surface (run_spacing_seconds), so every reservation K still holds is
+   older than that window and its holder is visible now, or it leaked.
+2. The counter moves only into [|V_N ∩ V_N+1|, |V_N ∪ V_N+1|], where V is
+   the set of holder identities attributed to K at a run. A holder keeps its
+   slot until it has been absent from two consecutive runs -- #513
+   constraints 4 (a missing worker key) and 7 (a record whose holder is not
+   visible) -- and earns a slot the counter lacks only once present at two
+   consecutive runs. That also absorbs the two short races a single snapshot
+   would lose: a holder that vanished just before its release lands (the
+   relay unregisters a channel before its release POST; a VOD session drops
+   to active_streams 0 a moment before its release), and a holder that
+   became visible just before its reserve lands (a VOD session reused by a
+   second request increments active_streams before it re-reserves).
+
+An unreachable relay skips the run entirely and leaves the snapshot alone
+(#513 constraint 3). relay_client.live_connections fails open by design, and
+here that rule inverts: an empty live set would lower every live profile to
+its VOD and catch-up share and lift the cap for every running channel.
+
+Runs on the worker role, from a beat entry (dispatcharr/settings.py) every
+BEAT_INTERVAL_SECONDS; the spacing is enforced here against Redis's own
+clock, so an edited beat interval, a backlog of queued runs or two worker
+containers can make runs no closer than run_spacing_seconds() apart.
+"""
+
+from __future__ import annotations
+
+import json
+import logging
+from dataclasses import dataclass, field
+
+from django.core.exceptions import ImproperlyConfigured
+
+from apps.m3u.connection_pool import (
+    credential_reservation,
+    profile_connections_key,
+    profile_credential_release_key,
+    read_slot_versions,
+    reconcile_counter,
+)
+
+logger = logging.getLogger(__name__)
+
+SNAPSHOT_KEY = "slot_reconciler:snapshot"
+LOCK_KEY = "slot_reconciler:lock"
+LOCK_TTL_SECONDS = 120
+BEAT_INTERVAL_SECONDS = 30.0
+MIN_SPACING_SECONDS = 60.0
+SPACING_FACTOR = 2
+SNAPSHOT_TTL_RUNS = 10
+
+VOD_KEY_PATTERN = "vod_persistent_connection:*"
+_ENDED_RELAY_STATES = frozenset({"stopped", "error"})
+
+
+def in_flight_windows() -> dict:
+    """The longest a reservation can go unseen on each surface, in seconds.
+
+    live:     the relay's tune budget, the bound on the next-source call inside
+              which Channel.get_stream() reserves and after which the relay
+              lists the channel (relay/httpapi/stream.go's tuneBudget, from
+              the same constants apps/proxy/control_plane.py exports).
+    vod:      the upstream connect-plus-first-byte timeout, per attempt, times
+              the attempts (the reserve precedes the provider GET).
+    catch_up: the pool lock's wait plus the operator-editable connect and
+              chunk timeouts _open_upstream passes to requests.
+    """
+    from apps.proxy import control_plane
+    from apps.proxy.config_helper import ConfigHelper
+    from apps.proxy.vod_proxy.multi_worker_connection_manager import (
+        UPSTREAM_ATTEMPTS,
+        UPSTREAM_TIMEOUT,
+    )
+    from apps.timeshift.views import POOL_LOCK_WAIT_SECONDS
+
+    live = (
+        control_plane.ATTEMPTS * (control_plane.CONNECT_TIMEOUT + control_plane.READ_TIMEOUT)
+        + control_plane.RETRY_DELAY
+    )
+    vod = UPSTREAM_ATTEMPTS * sum(UPSTREAM_TIMEOUT)
+    catch_up = (
+        POOL_LOCK_WAIT_SECONDS
+        + float(ConfigHelper.connection_timeout())
+        + float(ConfigHelper.chunk_timeout())
+    )
+    return {"live": float(live), "vod": float(vod), "catch_up": float(catch_up)}
+
+
+def run_spacing_seconds(windows=None) -> float:
+    """How far apart two runs must be: SPACING_FACTOR times the widest window, floored."""
+    windows = windows or in_flight_windows()
+    return max(MIN_SPACING_SECONDS, SPACING_FACTOR * max(windows.values()))
+
+
+@dataclass
+class RunResult:
+    status: str  # "skipped", "snapshot" (first run: nothing to compare), "reconciled"
+    reason: str = ""
+    changes: list = field(default_factory=list)
+
+    def as_dict(self):
+        return {"status": self.status, "reason": self.reason, "changes": self.changes}
+
+
+def _text(value):
+    return value.decode() if isinstance(value, bytes) else value
+
+
+def _int(value, default=0):
+    try:
+        return int(float(_text(value)))
+    except (TypeError, ValueError):
+        return default
+
+
+class SlotReconciler:
+    def __init__(self, redis_client=None, *, clock=None, list_channels=None):
+        if redis_client is None:
+            from core.utils import RedisClient
+
+            redis_client = RedisClient.get_client()
+        self.redis = redis_client
+        self._clock = clock or self._redis_time
+        if list_channels is None:
+            from apps.proxy import relay_client
+
+            list_channels = relay_client.list_channels
+        self._list_channels = list_channels
+
+    def _redis_time(self):
+        seconds, micros = self.redis.time()
+        return seconds + micros / 1_000_000
+
+    # -- counters -----------------------------------------------------------
+
+    def _counters(self):
+        """The counters an admission check reads, from today's configuration.
+
+        Returns (every counter key, {profile id: its profile counter},
+        {profile id: the credential counter its configuration names}). A
+        profile counter exists only for max_streams > 0 (a reserve does not
+        count an unlimited profile); a credential counter for each pooled,
+        limited profile with a fingerprint, shared by every profile whose
+        login maps to it.
+        """
+        from apps.m3u.models import M3UAccountProfile
+
+        profile_counter, config_credential = {}, {}
+        profiles = M3UAccountProfile.objects.filter(max_streams__gt=0).select_related(
+            "m3u_account__server_group"
+        )
+        for profile in profiles:
+            profile_counter[profile.id] = profile_connections_key(profile.id)
+            cred_key, _cap = credential_reservation(profile)
+            if cred_key:
+                config_credential[profile.id] = cred_key
+        keys = set(profile_counter.values()) | set(config_credential.values())
+        return keys, profile_counter, config_credential
+
+    def _credential_attribution(self, profile_ids, config_credential):
+        """{profile id: the credential counter its holders count against}.
+
+        The counter the profile's release pointer names, which is what its
+        last reserve or switch counted against whatever its configuration says
+        now; else the one its configuration names today.
+        """
+        profile_ids = sorted(profile_ids)
+        if not profile_ids:
+            return {}
+        pointers = self.redis.mget([profile_credential_release_key(p) for p in profile_ids])
+        attribution = {}
+        for profile_id, pointer in zip(profile_ids, pointers):
+            key = _text(pointer) or config_credential.get(profile_id)
+            if key:
+                attribution[profile_id] = key
+        return attribution
+
+    # -- ground truth ---------------------------------------------------------
+
+    def _live_holders(self, channels):
+        holders = {}
+        for channel in channels:
+            profile_id = channel.get("m3u_profile_id")
+            if not profile_id or channel.get("state") in _ENDED_RELAY_STATES:
+                continue
+            holders[f"live:{channel.get('channel_id')}"] = int(profile_id)
+        return holders
+
+    def _scan_hashes(self, pattern, fields):
+        # By type, never by key shape: a client-chosen session id may contain
+        # ':'. timeshift:pool:<s>:lock and :superseded are strings, not hashes.
+        records = {}
+        for key in self.redis.scan_iter(match=pattern, count=1000, _type="hash"):
+            key = _text(key)
+            values = self.redis.hmget(key, fields)
+            records[key] = dict(zip(fields, (_text(v) for v in values)))
+        return records
+
+    def _alive(self, worker_ids):
+        from apps.proxy.vod_proxy.held_records import worker_key
+
+        worker_ids = sorted({w for w in worker_ids if w})
+        if not worker_ids:
+            return set()
+        present = self.redis.mget([worker_key(w) for w in worker_ids])
+        return {w for w, value in zip(worker_ids, present) if value is not None}
+
+    def _record_holders(self, now, vod_window):
+        from apps.timeshift.redis_keys import TimeshiftRedisKeys
+
+        vod = self._scan_hashes(
+            VOD_KEY_PATTERN,
+            ["m3u_profile_id", "active_streams", "worker_id", "created_at"],
+        )
+        pool = self._scan_hashes(
+            TimeshiftRedisKeys.pool_scan_pattern(),
+            ["profile_id", "busy", "worker_id"],
+        )
+        alive = self._alive(
+            [r["worker_id"] for r in vod.values()] + [r["worker_id"] for r in pool.values()]
+        )
+        holders = {}
+        for key, r in vod.items():
+            profile_id = _int(r["m3u_profile_id"], None)
+            if not profile_id:
+                continue
+            active = _int(r["active_streams"])
+            if active > 0 and r["worker_id"] in alive:
+                holders[f"vod:{key}"] = profile_id
+            elif active <= 0 and now - _int(r["created_at"], 0) < vod_window:
+                # Seeded, not started: the reserve preceded the provider GET.
+                holders[f"vod:{key}"] = profile_id
+        for key, r in pool.items():
+            profile_id = _int(r["profile_id"], None)
+            if profile_id and r["busy"] == "1" and r["worker_id"] in alive:
+                holders[f"catchup:{key}"] = profile_id
+        return holders
+
+    # -- snapshot -------------------------------------------------------------
+
+    def _load_snapshot(self):
+        raw = self.redis.get(SNAPSHOT_KEY)
+        if not raw:
+            return None
+        try:
+            data = json.loads(_text(raw))
+            return float(data["taken_at"]), {
+                k: (int(v[0]), set(v[1])) for k, v in data["counters"].items()
+            }
+        except (ValueError, KeyError, TypeError):
+            logger.warning("Slot reconciler: discarding an unreadable snapshot")
+            return None
+
+    def _save_snapshot(self, taken_at, versions, identities, spacing):
+        payload = {
+            "taken_at": taken_at,
+            "counters": {
+                k: [versions.get(k, 0), sorted(identities.get(k, ()))] for k in versions
+            },
+        }
+        self.redis.set(
+            SNAPSHOT_KEY, json.dumps(payload), ex=int(max(spacing * SNAPSHOT_TTL_RUNS, 600))
+        )
+
+    # -- the run --------------------------------------------------------------
+
+    def run(self) -> RunResult:
+        lock = self.redis.lock(LOCK_KEY, timeout=LOCK_TTL_SECONDS)
+        if not lock.acquire(blocking=False):
+            return RunResult("skipped", "another run holds the lock")
+        try:
+            return self._run()
+        finally:
+            try:
+                lock.release()
+            except Exception:
+                pass
+
+    def _run(self) -> RunResult:
+        windows = in_flight_windows()
+        spacing = run_spacing_seconds(windows)
+        previous = self._load_snapshot()
+        # ORM first: no Redis read is older than it needs to be.
+        counter_keys, profile_counter, config_credential = self._counters()
+
+        # The version read and its timestamp come BEFORE any ground truth is
+        # read: the next run's safety argument measures the spacing from here.
+        taken_at = self._clock()
+        if previous is not None and taken_at - previous[0] < spacing:
+            return RunResult("skipped", f"less than {spacing:.0f}s since the last snapshot")
+        versions = read_slot_versions(counter_keys, self.redis)
+
+        try:
+            answer = self._list_channels()
+        except ImproperlyConfigured as exc:
+            logger.warning(
+                "Slot reconciler skipped: %s is misconfigured",
+                getattr(exc, "var_name", None) or "the relay base URL",
+            )
+            return RunResult("skipped", "relay misconfigured")
+        except Exception as exc:
+            from apps.proxy import relay_client
+
+            if isinstance(exc, (relay_client.RelayUnavailable, relay_client.RelayRefused)):
+                logger.warning("Slot reconciler skipped: the relay could not answer: %s", exc)
+                return RunResult("skipped", "relay unavailable")
+            raise
+        channels = answer.get("channels") if isinstance(answer, dict) else None
+        if not isinstance(channels, list):
+            # A 2xx body with no channel list is not an empty live set.
+            logger.warning("Slot reconciler skipped: the relay's answer carried no channel list")
+            return RunResult("skipped", "relay answer unusable")
+
+        by_profile = {}
+        for identity, profile_id in self._live_holders(channels).items():
+            by_profile.setdefault(profile_id, set()).add(identity)
+        for identity, profile_id in self._record_holders(taken_at, windows["vod"]).items():
+            by_profile.setdefault(profile_id, set()).add(identity)
+        identities = {key: set() for key in counter_keys}
+        for profile_id, key in profile_counter.items():
+            identities[key] |= by_profile.get(profile_id, set())
+        for profile_id, key in self._credential_attribution(by_profile, config_credential).items():
+            if key in identities:
+                identities[key] |= by_profile[profile_id]
+
+        changes = []
+        if previous is not None:
+            _then, before = previous
+            for key, now_ids in identities.items():
+                if key not in before:
+                    continue
+                expected, then_ids = before[key]
+                if versions.get(key) != expected:
+                    continue  # written since the last run: wait for a quiet interval
+                floor = len(then_ids & now_ids)
+                ceiling = len(then_ids | now_ids)
+                status, was, became = reconcile_counter(key, expected, floor, ceiling, self.redis)
+                if status == 1:
+                    changes.append({"counter": key, "from": was, "to": became})
+                    logger.info(
+                        "Slot reconciler moved %s from %s to %s (holders: %s at both runs, %s at either)",
+                        _loggable(key), was, became, floor, ceiling,
+                    )
+        self._save_snapshot(taken_at, versions, identities, spacing)
+        if previous is None:
+            logger.info("Slot reconciler took its first snapshot of %s counters", len(identities))
+            return RunResult("snapshot")
+        return RunResult("reconciled", changes=changes)
+
+
+def _loggable(counter_key: str) -> str:
+    """A counter's name without the credential fingerprint it embeds."""
+    if counter_key.startswith("server_group_connections:"):
+        group = counter_key.split(":")[1]
+        return f"the shared-login counter of server group {group}"
+    return counter_key
+
+
+def reconcile_provider_slots() -> dict:
+    return SlotReconciler().run().as_dict()
diff --git a/apps/proxy/tests/test_slot_reconciler.py b/apps/proxy/tests/test_slot_reconciler.py
new file mode 100644
index 00000000..9eb83475
--- /dev/null
+++ b/apps/proxy/tests/test_slot_reconciler.py
@@ -0,0 +1,503 @@
+"""The provider-slot reconciler, against a live Redis and the test database (#513).
+
+The eleven tests #513 names, each an interleaving the reconciler must survive
+without dropping a slot a live holder owns, plus the derived run spacing and
+the beat entry. Redis is real because the property under test is what the
+slot script does atomically at write time; the relay is a stub whose answer
+each test sets; time is a fake clock the test advances past the run spacing.
+Without Redis these skip, except under CI, where they fail.
+"""
+
+from __future__ import annotations
+
+import os
+import uuid
+from unittest import mock
+
+from django.core.exceptions import ImproperlyConfigured
+from django.test import TestCase
+
+from apps.channels.models import Channel, ChannelStream, Stream
+from apps.m3u.connection_pool import (
+    credential_reservation,
+    profile_connections_key,
+    release_profile_slot,
+    reserve_profile_slot,
+    slot_version_key,
+)
+from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup
+from apps.proxy import relay_client, slot_reconciler
+from apps.proxy.slot_reconciler import (
+    LOCK_KEY,
+    SNAPSHOT_KEY,
+    SlotReconciler,
+    in_flight_windows,
+    run_spacing_seconds,
+)
+from apps.proxy.vod_proxy.held_records import HeldRecords, worker_key
+
+
+def _live_redis():
+    from core.utils import RedisClient
+
+    try:
+        client = RedisClient.get_client(max_retries=1, retry_interval=0)
+        if client is not None and client.ping():
+            return client
+    except Exception:
+        pass
+    return None
+
+
+class ReconcilerTestCase(TestCase):
+    redis = None
+
+    @classmethod
+    def setUpClass(cls):
+        super().setUpClass()
+        cls.redis = _live_redis()
+
+    def setUp(self):
+        if self.redis is None:
+            if os.environ.get("CI"):
+                self.fail("Redis is not reachable under CI: these tests must run, not skip")
+            self.skipTest("Redis not available")
+        self.tag = uuid.uuid4().hex[:10]
+        self.now = 1_000_000.0
+        self.channels = []
+        self.relay_error = None
+        self.relay_answer = None  # when set, returned verbatim instead of the channel list
+        self.cleanup = [SNAPSHOT_KEY, LOCK_KEY]
+        self.redis.delete(SNAPSHOT_KEY, LOCK_KEY)
+        self.addCleanup(self._clean)
+        self.group = ServerGroup.objects.create(name=f"g-{self.tag}")
+        self.account = M3UAccount.objects.create(
+            name=f"acct-{self.tag}", account_type="XC", username="user", password="pass",
+            server_url="http://xc.example.com", server_group=self.group, max_streams=10,
+        )
+        self.p1 = M3UAccountProfile.objects.get(m3u_account=self.account, is_default=True)
+        self.p1.max_streams = 5
+        self.p1.save()
+        self.p2 = M3UAccountProfile.objects.create(
+            m3u_account=self.account, name=f"p2-{self.tag}", is_default=False,
+            is_active=True, max_streams=5, search_pattern="", replace_pattern="",
+        )
+
+    def _clean(self):
+        keys = set(self.cleanup)
+        for profile in M3UAccountProfile.objects.filter(m3u_account=self.account):
+            pk = profile_connections_key(profile.id)
+            keys |= {pk, slot_version_key(pk), f"profile_credential_release:{profile.id}"}
+            cred, _cap = credential_reservation(profile)
+            if cred:
+                keys |= {cred, slot_version_key(cred)}
+        self.redis.delete(*keys)
+
+    # -- drivers --------------------------------------------------------------
+
+    def list_channels(self):
+        if self.relay_error is not None:
+            raise self.relay_error
+        if self.relay_answer is not None:
+            return self.relay_answer
+        return {"channels": list(self.channels), "count": len(self.channels)}
+
+    def run_once(self):
+        return SlotReconciler(
+            self.redis, clock=lambda: self.now, list_channels=self.list_channels
+        ).run()
+
+    def tick(self):
+        self.now += run_spacing_seconds() + 1
+
+    def live(self, profile, name):
+        return {"channel_id": f"{self.tag}-{name}", "state": "active", "m3u_profile_id": profile.id}
+
+    def count(self, profile):
+        return int(self.redis.get(profile_connections_key(profile.id)) or 0)
+
+    def vod_hash(self, name, profile, *, active, worker, created_at=None, last_activity=None):
+        key = f"vod_persistent_connection:{self.tag}-{name}"
+        self.cleanup.append(key)
+        self.redis.hset(key, mapping={
+            "m3u_profile_id": profile.id,
+            "active_streams": active,
+            "worker_id": worker,
+            "created_at": self.now if created_at is None else created_at,
+            "last_activity": self.now if last_activity is None else last_activity,
+        })
+        return key
+
+    def cred_count(self, profile):
+        cred, _cap = credential_reservation(profile)
+        return int(self.redis.get(cred) or 0)
+
+    def pool_entry(self, name, profile, *, worker, busy="1"):
+        key = f"timeshift:pool:{self.tag}-{name}"
+        self.cleanup.append(key)
+        self.redis.hset(key, mapping={"profile_id": profile.id, "busy": busy, "worker_id": worker})
+        return key
+
+    def live_worker(self, name):
+        worker = f"host-{self.tag}-{name}"
+        self.cleanup.append(worker_key(worker))
+        HeldRecords(self.redis, worker).refresh_once()
+        return worker
+
+
+class OrphanTests(ReconcilerTestCase):
+    def test_an_orphan_is_dropped_after_two_absent_runs(self):
+        # A relay-go crash: the channel held a slot, the relay restarted
+        # empty, and no release will ever come.
+        reserve_profile_slot(self.p1, self.redis)
+        self.channels = [self.live(self.p1, "a")]
+        self.run_once()
+        self.channels = []
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 1, "an orphan was dropped after one absent run")
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 0, "an orphan absent from two runs kept its slot")
+
+
+class InFlightTests(ReconcilerTestCase):
+    """A reservation whose holder is not visible yet must survive a run."""
+
+    def _assert_survives(self, surface, reserve, visible):
+        self.channels = [self.live(self.p1, "steady")]
+        reserve_profile_slot(self.p1, self.redis)  # the steady holder
+        self.run_once()
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 1)
+        reserve()  # after this run's snapshot: in flight, not visible yet
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 2, f"an in-flight {surface} reservation was released")
+        visible()
+        self.tick()
+        self.run_once()
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 2)
+
+    def test_an_in_flight_live_reservation_is_not_released(self):
+        self._assert_survives(
+            "live",
+            lambda: reserve_profile_slot(self.p1, self.redis),  # get_stream(), before the relay lists it
+            lambda: self.channels.append(self.live(self.p1, "new")),
+        )
+
+    def test_an_in_flight_vod_reservation_is_not_released(self):
+        worker = self.live_worker("vod")
+        self._assert_survives(
+            "VOD",
+            lambda: reserve_profile_slot(self.p1, self.redis),  # mwcm reserves before creating the hash
+            lambda: self.vod_hash("new", self.p1, active=1, worker=worker),
+        )
+
+    def test_an_in_flight_catch_up_reservation_is_not_released(self):
+        worker = self.live_worker("cu")
+        self._assert_survives(
+            "catch-up",
+            lambda: reserve_profile_slot(self.p1, self.redis),  # reserved; the pool lock not yet taken
+            lambda: self.pool_entry("new", self.p1, worker=worker),
+        )
+
+
+class ReleaseThenTuneTests(ReconcilerTestCase):
+    def test_a_release_then_a_tune_between_runs_is_not_clobbered(self):
+        # R3-1's interleaving, where value stability fails: the counter reads 1
+        # at run A and at run B, but it counts a different reservation each
+        # time, and neither holder is visible at either run.
+        self.run_once()  # the baseline: nothing held
+        self.tick()
+        reserve_profile_slot(self.p1, self.redis)  # tune x, in flight at A
+        self.run_once()  # A: the version moved, so no write; the snapshot records 1
+        release_profile_slot(self.p1.id, self.redis)  # x's connect fails
+        reserve_profile_slot(self.p1, self.redis)  # tune y, in flight at B
+        self.tick()
+        self.run_once()  # B
+        self.assertEqual(self.count(self.p1), 1, "a release then a tune between runs lost the tune's slot")
+
+
+class FailoverTests(ReconcilerTestCase):
+    def test_a_profile_changing_failover_between_runs_is_not_clobbered(self):
+        stream = Stream.objects.create(
+            name=f"s-{self.tag}", url="http://xc.example.com/live/user/pass/1.ts",
+            m3u_account=self.account,
+        )
+        channel = Channel.objects.create(channel_number=900, name=f"c-{self.tag}")
+        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
+        self.cleanup += [f"channel_stream:{channel.id}", f"stream_profile:{stream.id}"]
+        with mock.patch.object(relay_client, "channel_snapshot"):
+            stream_id, profile_id, _err, reserved = channel.get_stream()
+        self.assertEqual((profile_id, reserved), (self.p1.id, True))
+        self.channels = [self.live(self.p1, "c")]
+        self.run_once()
+        # Failover: next-source's _commit moves the slot to p2. The relay's
+        # list still says p1 until it takes up the new answer.
+        self.assertTrue(channel.update_stream_profile(self.p2.id))
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p2), 1, "a failover's reservation on the new profile was dropped")
+        self.assertEqual(self.count(self.p1), 0)
+
+
+class RefusedReserveTests(ReconcilerTestCase):
+    def test_a_refused_reserve_does_not_trigger_a_write(self):
+        self.p1.max_streams = 1
+        self.p1.save()
+        reserve_profile_slot(self.p1, self.redis)
+        self.channels = [self.live(self.p1, "a")]
+        self.run_once()
+        key = profile_connections_key(self.p1.id)
+        version = int(self.redis.get(slot_version_key(key)) or 0)
+        self.assertEqual(reserve_profile_slot(self.p1, self.redis)[0], False)
+        self.assertEqual(
+            int(self.redis.get(slot_version_key(key)) or 0), version,
+            "a refused reserve moved the counter's version",
+        )
+        self.tick()
+        result = self.run_once()
+        self.assertEqual(result.changes, [], "a refused reserve made the reconciler write")
+        self.assertEqual(self.count(self.p1), 1)
+
+    def test_a_refused_reserve_does_not_block_a_due_correction(self):
+        # The same refusal, on a counter that has leaked one slot: the leak is
+        # still corrected on schedule, because the refusal moved no version.
+        self.p1.max_streams = 2
+        self.p1.save()
+        reserve_profile_slot(self.p1, self.redis)
+        reserve_profile_slot(self.p1, self.redis)  # the second one leaked
+        self.channels = [self.live(self.p1, "a")]
+        self.run_once()
+        self.tick()
+        # A viewer retrying against the full profile. At the seed each refusal
+        # was an INCR then a DECR -- two writes -- so a profile refusing once
+        # per interval would never be quiet long enough to correct.
+        self.assertFalse(reserve_profile_slot(self.p1, self.redis)[0])
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 1, "a refused reserve blocked the leak's correction")
+
+
+class RelayUnreachableTests(ReconcilerTestCase):
+    def test_an_unreachable_relay_leaves_every_counter_untouched(self):
+        for error in (
+            relay_client.RelayUnavailable("down", transport=True),
+            relay_client.RelayRefused(403, "/proxy/relay/channels"),
+            ImproperlyConfigured("DISPATCHARR_RELAY_BASE_URL"),
+        ):
+            with self.subTest(error=type(error).__name__):
+                self.redis.delete(SNAPSHOT_KEY)
+                self.redis.set(profile_connections_key(self.p1.id), 3)  # drifted, no holder anywhere
+                self.channels = []
+                self.relay_error = None
+                self.run_once()
+                snapshot = self.redis.get(SNAPSHOT_KEY)
+                self.relay_error = error
+                for _ in range(3):
+                    self.tick()
+                    result = self.run_once()
+                    self.assertEqual(result.status, "skipped", "an unreachable relay did not skip the run")
+                self.assertEqual(self.count(self.p1), 3, "an unreachable relay moved profile_connections")
+                self.assertEqual(self.redis.get(SNAPSHOT_KEY), snapshot)
+
+
+class RelayAnswerTests(ReconcilerTestCase):
+    def test_a_relay_answer_without_a_channel_list_skips_the_run(self):
+        # A 2xx body with no list must not read as "no live channels".
+        for answer in ({}, {"channels": None}, {"channels": "garbled"}, ["not", "an", "object"]):
+            with self.subTest(answer=answer):
+                self.redis.delete(SNAPSHOT_KEY)
+                self.redis.set(profile_connections_key(self.p1.id), 3)
+                self.relay_answer = None
+                self.run_once()
+                snapshot = self.redis.get(SNAPSHOT_KEY)
+                self.relay_answer = answer
+                for _ in range(3):
+                    self.tick()
+                    self.assertEqual(
+                        self.run_once().status, "skipped",
+                        "a relay answer with no channel list was read as an empty live set",
+                    )
+                self.assertEqual(self.count(self.p1), 3)
+                self.assertEqual(self.redis.get(SNAPSHOT_KEY), snapshot)
+
+
+class ColonSessionIdTests(ReconcilerTestCase):
+    """A client chooses both session ids (VOD's path segment, catch-up's
+    ?session_id=), and either may contain ':'. Such a holder is still a holder."""
+
+    def _assert_kept(self, surface, make_holder):
+        worker = self.live_worker(surface)
+        reserve_profile_slot(self.p1, self.redis)
+        make_holder(worker)
+        for _ in range(3):
+            self.run_once()
+            self.tick()
+        self.assertEqual(
+            self.count(self.p1), 1,
+            f"a live {surface} holder with ':' in its session id lost its slot",
+        )
+
+    def test_a_vod_holder_with_a_colon_in_its_session_id_keeps_its_slot(self):
+        self._assert_kept("VOD", lambda w: self.vod_hash("a:b", self.p1, active=1, worker=w))
+
+    def test_a_catch_up_holder_with_a_colon_in_its_session_id_keeps_its_slot(self):
+        def holder(worker):
+            self.pool_entry("a:b", self.p1, worker=worker)
+            # The pool's lock and superseded marker share the key prefix and
+            # are strings, not hashes; they must neither count nor break the scan.
+            for suffix in ("lock", "superseded"):
+                key = f"timeshift:pool:{self.tag}-other:{suffix}"
+                self.cleanup.append(key)
+                self.redis.set(key, "1")
+
+        self._assert_kept("catch-up", holder)
+
+
+class CredentialAttributionTests(ReconcilerTestCase):
+    """A shared-login counter counts what was reserved against it, not what
+    the configuration would reserve against it today."""
+
+    def _two_live_streams_on_one_login(self):
+        self.assertEqual(credential_reservation(self.p1)[0], credential_reservation(self.p2)[0])
+        reserve_profile_slot(self.p1, self.redis)
+        reserve_profile_slot(self.p2, self.redis)
+        self.channels = [self.live(self.p1, "a"), self.live(self.p2, "b")]
+        self.assertEqual(self.cred_count(self.p2), 2)
+        self.run_once()
+
+    def _assert_still_two(self):
+        for _ in range(3):
+            self.tick()
+            self.run_once()
+        self.assertEqual(
+            self.cred_count(self.p2), 2, "the shared-login counter dropped under two live streams"
+        )
+
+    def test_making_a_pooled_profile_unlimited_mid_stream_keeps_its_holders_counted(self):
+        self._two_live_streams_on_one_login()
+        self.p1.max_streams = 0
+        self.p1.save()
+        self._assert_still_two()
+
+    def test_deleting_a_pooled_profile_mid_stream_keeps_its_holders_counted(self):
+        self._two_live_streams_on_one_login()
+        self.cleanup.append(f"profile_credential_release:{self.p1.id}")
+        self.p1.delete()
+        self._assert_still_two()
+
+
+class WorkerLivenessTests(ReconcilerTestCase):
+    def test_a_paused_viewer_is_counted_while_its_worker_lives_and_dropped_two_runs_after_it_dies(self):
+        vod_worker = self.live_worker("vod")
+        cu_worker = self.live_worker("cu")
+        reserve_profile_slot(self.p1, self.redis)
+        reserve_profile_slot(self.p2, self.redis)
+        # Two hours since either moved a byte: recency would call both dead.
+        self.vod_hash("paused", self.p1, active=1, worker=vod_worker, last_activity=self.now - 7200)
+        self.pool_entry("paused", self.p2, worker=cu_worker)
+        for _ in range(4):
+            self.run_once()
+            self.tick()
+        self.assertEqual(
+            (self.count(self.p1), self.count(self.p2)), (1, 1),
+            "a paused viewer with a live worker lost its slot",
+        )
+        self.redis.delete(worker_key(vod_worker), worker_key(cu_worker))  # both processes die
+        self.run_once()
+        self.assertEqual((self.count(self.p1), self.count(self.p2)), (1, 1),
+                         "a dead worker's records dropped after one run")
+        self.tick()
+        self.run_once()
+        self.assertEqual((self.count(self.p1), self.count(self.p2)), (0, 0),
+                         "a dead worker's records were still counted two runs after it died")
+
+
+class SeededHashTests(ReconcilerTestCase):
+    def test_a_seeded_never_started_hash_is_not_counted_past_its_window(self):
+        window = in_flight_windows()["vod"]
+        reserve_profile_slot(self.p1, self.redis)
+        self.vod_hash("seeded", self.p1, active=0, worker="host-that-died-1", created_at=self.now)
+        self.run_once()
+        self.now += window - 1
+        self.redis.delete(SNAPSHOT_KEY)  # a fresh baseline inside the window
+        self.run_once()
+        self.tick()
+        self.run_once()
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 0, "a seeded hash was counted past the VOD window")
+
+    def test_a_seeded_hash_inside_its_window_is_counted(self):
+        self.p1.max_streams = 5
+        self.p1.save()
+        self.redis.set(profile_connections_key(self.p1.id), 0)  # the reserve's count was lost
+        self.vod_hash("seeded", self.p1, active=0, worker="w", created_at=self.now + 10 * run_spacing_seconds())
+        self.run_once()
+        self.tick()
+        self.run_once()
+        self.assertEqual(self.count(self.p1), 1, "a seeded hash inside its window was not counted")
+
+
+class ConcurrentIncrTests(ReconcilerTestCase):
+    def test_a_concurrent_incr_is_not_clobbered(self):
+        reserve_profile_slot(self.p1, self.redis)  # leaked: nothing ever lists it
+        self.run_once()
+        self.tick()
+        real = slot_reconciler.reconcile_counter
+
+        def racing(key, expected, floor, ceiling, client):
+            if key == profile_connections_key(self.p1.id):
+                reserve_profile_slot(self.p1, self.redis)  # lands between the reads and the write
+            return real(key, expected, floor, ceiling, client)
+
+        with mock.patch.object(slot_reconciler, "reconcile_counter", side_effect=racing):
+            self.run_once()
+        self.assertEqual(self.count(self.p1), 2, "a concurrent INCR was clobbered")
+
+
+class SpacingTests(ReconcilerTestCase):
+    def test_the_spacing_follows_the_widest_window_including_operator_settings(self):
+        from apps.proxy import control_plane
+        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
+            UPSTREAM_ATTEMPTS,
+            UPSTREAM_TIMEOUT,
+        )
+        from apps.timeshift.views import POOL_LOCK_WAIT_SECONDS
+
+        windows = in_flight_windows()
+        # The relay's tuneBudget, from the constants it is built from.
+        self.assertAlmostEqual(
+            windows["live"],
+            control_plane.ATTEMPTS * (control_plane.CONNECT_TIMEOUT + control_plane.READ_TIMEOUT)
+            + control_plane.RETRY_DELAY,
+        )
+        self.assertEqual(windows["vod"], UPSTREAM_ATTEMPTS * sum(UPSTREAM_TIMEOUT))
+        self.assertEqual(
+            run_spacing_seconds(windows),
+            max(slot_reconciler.MIN_SPACING_SECONDS, slot_reconciler.SPACING_FACTOR * max(windows.values())),
+        )
+        with mock.patch("apps.proxy.config_helper.ConfigHelper.connection_timeout", return_value=60), \
+                mock.patch("apps.proxy.config_helper.ConfigHelper.chunk_timeout", return_value=30):
+            self.assertEqual(
+                run_spacing_seconds(),
+                slot_reconciler.SPACING_FACTOR * (POOL_LOCK_WAIT_SECONDS + 60 + 30),
+            )
+
+    def test_the_default_spacing_is_80_seconds(self):
+        # One literal pin: at the shipped defaults the VOD window (40 s) wins.
+        self.assertEqual(run_spacing_seconds(), 80.0)
+
+    def test_a_run_inside_the_spacing_writes_nothing(self):
+        self.redis.set(profile_connections_key(self.p1.id), 2)  # leaked twice, never held
+        self.run_once()
+        self.now += run_spacing_seconds() - 1
+        self.assertEqual(self.run_once().status, "skipped")
+        self.assertEqual(self.count(self.p1), 2, "a run inside the spacing wrote a counter")
+        self.now += 2
+        self.run_once()  # absent at both runs, a full spacing apart
+        self.assertEqual(self.count(self.p1), 0)
diff --git a/apps/proxy/vod_proxy/multi_worker_connection_manager.py b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
index f9eed6db..8707f523 100644
--- a/apps/proxy/vod_proxy/multi_worker_connection_manager.py
+++ b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
@@ -97,6 +97,14 @@ return 1
 # generator holds the session, by this process's slot-holder refresher (#513).
 SESSION_TTL_SECONDS = 3600
 
+# The provider GET's (connect, first-byte) timeout, and how many GETs one
+# request can make (a cached final_url that errors is retried once from the
+# original stream_url). The provider-slot reconciler sizes its run spacing
+# from these (apps/proxy/slot_reconciler.py, #513): a reservation precedes
+# the GET, so a slot can go unseen for up to their product.
+UPSTREAM_TIMEOUT = (10, 10)
+UPSTREAM_ATTEMPTS = 2
+
 # Cache register_script handles per redis client (EVALSHA thereafter).
 _vod_script_cache: Dict[int, Dict[str, Any]] = {}
 
@@ -501,7 +509,7 @@ class RedisBackedVODConnection:
                 target_url,
                 headers=headers,
                 stream=True,
-                timeout=(10, 10),
+                timeout=UPSTREAM_TIMEOUT,
                 allow_redirects=allow_redirects
             )
 
@@ -520,7 +528,7 @@ class RedisBackedVODConnection:
                     state.stream_url,
                     headers=headers,
                     stream=True,
-                    timeout=(10, 10),
+                    timeout=UPSTREAM_TIMEOUT,
                     allow_redirects=True
                 )
 
diff --git a/apps/timeshift/views.py b/apps/timeshift/views.py
index 024e8f9c..962e3b0d 100644
--- a/apps/timeshift/views.py
+++ b/apps/timeshift/views.py
@@ -2132,11 +2132,17 @@ def _resolve_session_archive_scrub(descriptor, requested_timestamp):
     }
 
 
+# How long _pool_lock waits for the pool lock. A reserve precedes the busy
+# pool entry by up to this long, so the provider-slot reconciler adds it to
+# the catch-up in-flight window (apps/proxy/slot_reconciler.py, #513).
+POOL_LOCK_WAIT_SECONDS = 5
+
+
 def _pool_lock(redis_client, session_id):
     return redis_client.lock(
         TimeshiftRedisKeys.pool_lock(session_id),
         timeout=10,
-        blocking_timeout=5,
+        blocking_timeout=POOL_LOCK_WAIT_SECONDS,
     )
 
 
diff --git a/core/tasks.py b/core/tasks.py
index 81889a27..cbcb139f 100644
--- a/core/tasks.py
+++ b/core/tasks.py
@@ -458,6 +458,21 @@ def fetch_channel_stats():
         collect_garbage=True
     )
 
+@shared_task
+def reconcile_provider_slots():
+    """Recompute the provider-slot counters from ground truth (#513).
+
+    Scheduled every 30 s by dispatcharr/settings.py's beat entry; the
+    reconciler itself refuses to run closer together than its derived
+    spacing, so the tick is only an upper bound on how late a run starts.
+    """
+    # Function-local, as fetch_channel_stats above: a Celery child should not
+    # import the relay client and the VOD and catch-up modules to start.
+    from apps.proxy.slot_reconciler import reconcile_provider_slots as run
+
+    return run()
+
+
 @shared_task
 def rehash_streams(keys):
     """
diff --git a/core/tests/test_reconcile_provider_slots.py b/core/tests/test_reconcile_provider_slots.py
new file mode 100644
index 00000000..e6e987d5
--- /dev/null
+++ b/core/tests/test_reconcile_provider_slots.py
@@ -0,0 +1,20 @@
+"""The provider-slot reconciler's beat entry (#513).
+
+Here rather than beside the reconciler's own tests because it pins
+dispatcharr/settings.py and core/tasks.py, whose edits select core.tests.
+"""
+
+from django.conf import settings
+from django.test import SimpleTestCase
+
+from apps.proxy import slot_reconciler
+from core.tasks import reconcile_provider_slots
+
+
+class ReconcileProviderSlotsBeatEntryTests(SimpleTestCase):
+    def test_the_beat_entry_names_the_task_on_a_tick_shorter_than_the_spacing_floor(self):
+        entry = settings.CELERY_BEAT_SCHEDULE["reconcile-provider-slots"]
+        self.assertEqual(entry["task"], reconcile_provider_slots.name)
+        # The tick bounds how late a run starts; the reconciler enforces the
+        # spacing itself, so the tick must be shorter than the spacing's floor.
+        self.assertLess(entry["schedule"], slot_reconciler.MIN_SPACING_SECONDS)
diff --git a/dispatcharr/settings.py b/dispatcharr/settings.py
index 5f833556..f73f1c8f 100644
--- a/dispatcharr/settings.py
+++ b/dispatcharr/settings.py
@@ -461,6 +461,15 @@ CELERY_BEAT_SCHEDULE = {
         "task": "apps.m3u.tasks.check_account_expirations",
         "schedule": 86400.0,  # Once every 24 hours
     },
+    # Recompute the provider-slot counters from ground truth (#513). The tick
+    # is not the run interval: apps/proxy/slot_reconciler.py skips any run
+    # closer than its derived spacing (about 80s at default settings) to the
+    # last one. Here rather than in a seeding migration so beat re-asserts the
+    # schedule on every start; an operator can still disable the row.
+    "reconcile-provider-slots": {
+        "task": "core.tasks.reconcile_provider_slots",
+        "schedule": 30.0,
+    },
 }
 
 MEDIA_ROOT = BASE_DIR / "media"
diff --git a/docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md b/docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md
index be434731..c350fbca 100644
--- a/docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md
+++ b/docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md
@@ -174,3 +174,17 @@ unreachable. The relay never enforces `max_streams`; it asks.
   because Django still owns `reserve_profile_slot`/`release_profile_slot`,
   adding a second relay (Phase 2) or a second live surface never requires
   teaching the relay about a counter it does not own.
+- *Added 2026-09-26 (#513).* Keeping the slots in Django dropped the
+  proposal's "reconciliation, not commands" property, and nothing replaced
+  it until #513: the counters had no TTL and no owner lease, so a holder
+  that died without releasing (a relay crash, a release lost while the API
+  restarted, a relay-uwsgi crash under VOD) leaked a slot for good, and a
+  Redis restart or a non-atomic repair wrote one down under a live holder.
+  Since #513 every counter write goes through one Lua script that bumps a
+  per-counter version, and a beat task on the worker role
+  (`apps/proxy/slot_reconciler.py`) recomputes each counter from the
+  relay's channel list and the VOD and catch-up records whose workers are
+  alive, writing only when the version has not moved since its previous
+  run. The decision above is unchanged: the relay still never enforces
+  `max_streams`, and a reconciler run that cannot reach the relay does
+  nothing. ADR 0007 records why this was fix work rather than a phase.
```
<!-- appendix-C-end -->
