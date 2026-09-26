# 7. Phase 3 is closed, because Phase 2 met its charter

Date: 2026-09-26

## Status

Accepted

## Context

This rests on [ADR 0005](0005-the-relay-is-chosen-by-name-once-per-tune.md)
and [ADR 0006](0006-the-go-relay-keeps-its-state-in-memory-and-the-cutover-is-hard.md),
both unchanged. ADR 0005 kept provider slots in Django because three surfaces
share one counter. ADR 0006 put the live relay's state in Go process memory.

The programme's ladder was Phase 0 harden in place, Phase 1 extract the
boundary, Phase 2 optionally Go, Phase 3 remove Redis from the data path.
*Splitting the Planes*, the original extraction proposal, defined Phase 3 in
one paragraph of its § Sequencing and sized it at about one week:

> Once the relay owns its buffer in memory, remove the chunk keys entirely.
> Redis keeps coordination, broker, cache. This is where the scaling ceiling
> lifts.

Its scope was the **chunk keys**, and only those. The phases before it took
that scope apart piece by piece:

| Phase | What it delivered of Phase 3's charter |
|---|---|
| 1 PR 7 | Made the relay's Redis keys private behind `/proxy/relay/…`, "which is what makes Phase 3 possible later, not what performs it now" (Phase 1 spec § Non-goals) |
| 2 D2 | The ring buffer in Go process memory from day one; the lease, the follower path and the three fail-open paths deleted rather than ported. "Phase 3's live half is absorbed here" (Phase 2 spec D2; ADR 0006) |
| 2d-3 | The nginx flip. The suite's last grey-box Redis read went with it, and the `GREYBOX_REDIS` allowlist became empty |
| 2d-4 | Deleted `apps/proxy/live_proxy/` in a 30,675-line deletion across 156 files (`b6ae174b`), with the chunk keys, leases, client sets and switch requests |
| 2d-6 | Rewrote CLAUDE.md and CONTEXT.md to say Phase 3 was "smaller than its charter describes" |

A reassessment on 2026-09-26, measured at `aa6f376c3d`, put five numbers on
where that leaves the phase:

| Fact | Number |
|---|---|
| Redis round trips per live video byte | **0**. `relay/go.mod` names no dependency, there is no `relay/go.sum`, and `scripts/check_go_stdlib_only.sh` fails on any `redis` in `go list -deps` |
| The proposal's Phase 3 | "remove the chunk keys", ~1 week. Absorbed whole by Phase 2 D2 |
| Streaming-surface Redis left in non-test Python | 2 counter families, 1 release-pointer key, 2 assignment keys, 1 VOD session family and 13 catch-up key builders: about 200 call sites over ten files |
| Grey-box e2e tests a Phase 3 would have to rewrite | **0** |
| Code a "full" Phase 3 would port to Go | **7,971** non-blank lines (`vod_proxy` 3,094, `timeshift` 4,877) |

**What remains in Redis on the streaming surfaces is coordination, not
bytes.** The provider-slot counters (`profile_connections:{id}`,
`server_group_connections:{group}:{fp}`) and the release pointer beside them
are a shared count three surfaces reserve against, and ADR 0005 placed them in
Django on purpose. `channel_stream:*` and `stream_profile:*` are Django's own
assignment keys. The VOD session hashes and the catch-up pool entries let a
request on any greenlet find the session another one opened. None of these
buffers a byte: VOD and catch-up stream by passthrough and never did anything
else. The one per-byte Redis touch left in the tree is catch-up's stop-key
poll, two `GET`s per chunk of up to 256 KiB (`apps/timeshift/views.py:2347-2349`
and `:3550-3552`), which is a polling cadence rather than a storage decision.
That is the same division the proposal drew: "Redis keeps coordination,
broker, cache."

Three larger shapes were costed against that remainder:

- **B1**, moving the counters and assignment keys into Postgres.
- **B2**, moving the streaming-surface keys to their own Redis logical
  database.
- **C**, porting VOD and catch-up into the Go relay and holding slots in Go
  memory, which would retire `relay-uwsgi`.

The reassessment also found one real hazard, which no shape of Phase 3 fixes.
The slot counters carry no TTL, no owner lease and no reconciliation on any of
the three surfaces, and they drift in both directions. They over-count when a
release is lost: a release POST dropped while `api-uwsgi` restarts is logged
as "it stays counted" and never retried (`relay/httpapi/events.go:56-57`),
which makes a deploy a likely leak: every channel that ends while
`api-uwsgi` restarts keeps its slot counted. They also over-count on a relay or
`relay-uwsgi` crash. They under-count after a Redis restart, when a channel
that spanned it releases a slot some newer stream reserved
(`apps/proxy/next_source.py:1115-1132`).

## Decision

**Phase 3 is closed without being executed.** It is closed, not deferred: its
charter was met by Phase 2 D2, and the Redis that remains on the streaming
surfaces is coordination that Redis is the right tool for. The programme stops
after Phase 2.

**B1 is rejected.** A Postgres counter with no lease leaks on owner death
exactly as a Redis one does, and it would keep every over-count across a
restart that today at least clears them. Every reserve and release would also
become a write transaction, and on `relay-uwsgi` that transaction queues on
eight database connections shared by 1,600 greenlets
(`MAX_CONNS=8` at `dispatcharr/settings.py:273`, `gevent` at
`docker/uwsgi.relay.ini:54`). The session hashes stay in Redis
either way, so Redis stays on the request path. It is worse than today on the
properties that matter.

**C is rejected.** It is a second Phase 2 for a smaller benefit. It ports
about 8,000 lines with no parity matrix, 10,260 lines of Python tests that do
not survive a change of language, and an open byte-range defect surface. It
lands on the two directories upstream is still actively changing and the
fork's own tracker says are least correct, and it makes them a permanent hard
fork. It overturns ADR 0005's slot ruling rather than amending it. What it
would buy is one fewer process and a restart that resets every counter
coherently, and the second of those can be had in Python.

**B2 is not rejected, and it is not scheduled.** A separate logical database
would confine the per-tune `SCAN` walks of a stream-limited user to the
streaming keyspace and stop a cache `FLUSHDB` from clearing a counter. It
isolates neither memory nor eviction, since logical databases share one
`maxmemory`. It is worth doing only if the per-tune `SCAN` cost is ever
measured to matter.

**The proposal's reconciliation property is owed as a fix, not as a phase.**
The proposal specified "Reconciliation, not commands": Django periodically
states the full desired set, and drift self-heals. Nothing built it. ADR 0005
kept slots in Django and did not carry the reconciliation across with them,
which is how the counters came to depend entirely on every release arriving.
#513 restores the property as ordinary planned fix work: a recompute
reconciler that derives each counter from ground truth on all three surfaces
and converges it in both directions. #514 sits beside it, making catch-up's two
stop-key polls time-based in one file. Neither is a phase, and neither
reopens this one.

## Consequences

- **The ladder ends at Phase 2.** There is no Phase 3 to widen into. Work on
  VOD, catch-up or the counters is fix work against a named issue, planned and
  reviewed like any other.
- **`relay-uwsgi` stays.** VOD and catch-up stay Python, served by the relay
  uWSGI process on the locations `docker/nginx.conf` still routes there.
  The live path stays on `relay-go`.
- **Redis stays on DB 0** for Celery's broker and results, the Channels layer,
  the Django cache, the provider-slot counters, the assignment keys and the
  VOD and catch-up sessions. The shared blast radius CLAUDE.md records is
  unchanged, minus the video, which was its largest tenant.
- **The grey-box Redis bookmark is retired.** `e2e/fixtures/greybox/redis.ts`
  had no importer since stage 2d-3 and survived only as Phase 3's single grep
  for "every greybox test is rewritten or deleted". With Phase 3 closed it is
  deleted, along with the `GREYBOX_REDIS` capability and its guard test. A
  test that imports the deleted path now fails to typecheck, and a new Redis
  helper in a new file would be a new subprocess or introspection use, which
  the surviving `SUBPROCESS` and `CONTAINER_INTROSPECTION` allowlists still
  police by name. A `redis-cli` call added to a file already on both lists
  would pass unseen, but the retired guard, which matched only the helper's
  import path, had the same blind spot, so nothing regressed.
- **The counter drift is an open defect, tracked by #513.** Until it lands, a
  deploy that restarts `api-uwsgi` under running streams can leave provider
  slots counted with nobody holding them, and a Redis restart can lift a cap
  instead. #356, #470 and #471 are the known point defects in the same
  subsystem and stay tracked on their own.
- **The specs keep their history.** The Phase 1 and Phase 2 specs' sentences
  about "what remains of Phase 3" describe the plan as it stood when they were
  written. This ADR is where that plan ends.
