# 6. The Go relay keeps its state in memory, and the cutover is hard

Date: 2026-09-20

## Status

Accepted

## Context

This builds on [ADR 0005](0005-the-relay-is-chosen-by-name-once-per-tune.md),
which is unchanged: authorization is still Django's decision, made once per
tune, and provider slots still live in Django. What follows is the two
decisions Phase 2 made that ADR 0005 did not anticipate, and the three
couplings the cutover found.

Phase 1 split the relay into its own uWSGI process without moving any relay
internals: the same Django code, the same urlconf, the same Redis keys, a
different listener. Phase 2's question was whether to reimplement the live
byte path in Go, and the two sub-questions that decided its shape were **where
the new implementation keeps channel state** and **how it takes over from the
old one**.

Both had an obvious answer that was wrong for the same reason, and the reason
is the process count.

**On state.** The Python relay kept everything in Redis — the ownership lease,
the channel metadata hash, the client sets, the switch requests, and the video
bytes themselves in a ring buffer of ~256 KB chunks. None of that was a
storage decision. It was a *coordination* decision forced by four API uWSGI
workers plus the relay's one all serving the same channel: no channel state
could live in Python memory because there was no single Python process that
owned a channel. The ownership lease existed to elect one of them per channel,
and it was time-bounded rather than fenced — `StreamBuffer.add_chunk()` wrote
with no ownership check and no fencing token, so two owners interleaved chunks
at alternating monotonic indices and readers decoded a spliced stream with
every check passing. Phase 0 recorded that as a carried constraint the
extracted relay must not recreate.

The straightforward port keeps the Redis shapes and writes Go against them.
That reproduces the lease, and with it the defect, in a language where the
fencing fix would have been easier — and it pays Redis's round trip and its
serialisation for every chunk of every stream, which is the single largest
cost on the byte path and the thing Phase 3 was created to remove.

**On cutover.** ADR 0005 built a canary mechanism and this ADR's phase is the
one it was built for: `X-Relay-Name` on the authorize response, copied into
`$relay_name` by `auth_request_set`, mapped to an upstream *group*. A second
Go relay taking a subset of channels was supposed to be one map entry, one
`upstream` block and a Django-side assignment table. The temptation is to use
it: run both relays, move ten channels, watch, move the rest.

## Decision

**The Go relay keeps its channel state in process memory, not in Redis**
(spec D2), **and the cutover is a hard switch of nginx's live locations with
no canary period** (spec D3).

The two decisions are one decision. A canary needs two implementations serving
the same channel set concurrently, and two implementations that share no state
cannot do that: a viewer whose second request landed on the other relay would
find no channel, no buffer and no client registry. Choosing memory over Redis
is choosing to have exactly one live relay process at a time, and choosing one
process is what makes the lease unnecessary.

Concretely:

- `relay/channel`'s `Manager` holds one `Channel` per live channel behind one
  mutex. Ownership is a map entry. There is no lease, no heartbeat, no orphan
  sweep and nothing to fence.
- `relay/buffer`'s ring is per-channel and in-process: a 300-chunk /
  76,760,400-byte cap and the same 60-second retention the Python ring had,
  whichever binds first, sized from `BUFFER_CHUNK_SIZE` on the `next-source`
  answer rather than from a Go-side constant, so a `proxy_settings` edit still
  moves it.
- The client registry is likewise a map with no TTL, no heartbeat and no ghost
  sweep, because with one process a client entry cannot outlive the goroutine
  that made it.
- The Go binary opens no Postgres connection and no Redis connection and links
  no driver for either. `scripts/check_go_stdlib_only.sh` is the mechanical
  backstop, and there is no `relay/go.sum` at all — `go list -m all` prints
  exactly the one module.
- At stage 2d-3 four nginx locations moved from `uwsgi_pass` to
  `proxy_pass http://relay_go` in one commit — the three byte-path locations
  plus `^~ /proxy/relay/` — and stage 2d-4 deleted `apps/proxy/live_proxy/`.
  There was never a window in which both relays served live traffic.

What makes a hard cutover acceptable rather than reckless is that the
*evidence* was gathered ahead of it instead of during it: the relay parity
matrix enumerates every externally-observable live-path behaviour, each row
carrying the source it was derived from and a test that pins it, and every row
was held to parity before any location moved: 28 of the 30 by a passing
Go-side pin, and the other two — `server.py`'s greenlet topology and
`_execute_redis_command`'s swallowing — by being white-box-only properties of
the implementation being deleted, which carry a `retired:` sentinel because
there is no Go source to point a citation at. Deliberate divergences (spec
D5's two) are recorded as rows, not discovered as incidents.

## Consequences

- **The ownership lease defect is retired, not fixed.** There is no analogous
  defect in a single-owner-per-process design, so Phase 0's carried constraint
  closes by elimination. `e2e/COVERAGE.md` keeps the trace of the one grey-box
  row that could never provoke it from outside the container, as the record of
  a gap that closed the same way.
- **A relay restart drops every live viewer, and nothing makes that gradual.**
  There is no second relay to bleed connections onto. D6's fifteen-second
  drain (a client grace, a concurrent channel teardown that releases every
  provider slot, then `http.Server.Shutdown`, with three seconds reserved for
  the events flush) bounds the damage; it does not remove it. `relay-go`
  measured ~17.3s from `supervisorctl restart` to a fresh tune's first byte.
- **A rollback is a revert of the nginx flip, and only while the Python relay
  still exists.** Between stage 2d-3 and stage 2d-4 that was a one-file
  change. After 2d-4 it is a revert of 106 deletions, four renames and 43
  modifications: the package was 101 files, 97 deleted and four `git mv`'d
  into the Go module, plus nine standalone paths. The window was
  deliberately left open across one merge and deliberately closed.
- **ADR 0005's canary machinery is still there and is still right — it just
  does not apply at this grain.** `$relay_name` is set per relay-bound
  location from one process-wide `settings.RELAY_DEFAULT_NAME`, so the map can
  say "this deployment's relay is X"; it cannot say "these four locations
  resolve differently than those six". (`docker/nginx.conf`'s own comment
  says "five"; measured, it is four `proxy_pass http://relay_go` against six
  `uwsgi_pass $relay_upstream`, with two more naming `relay_py` literally and
  consulting no map at all.) The four flipped locations name
  `relay_go` literally and consult no map. The mechanism's real users are a
  future per-channel assignment table and horizontal scale-out, neither of
  which this phase needed.
- **Django still owns the live URL patterns even though Django no longer
  serves them.** `apps/proxy/authorize_views.py`'s `_surface_for()` resolves
  the tune URI through Django's own urlconf and keys on the resolved view's
  `__name__`, so the authorize hop for a URL Django cannot resolve fails
  closed. Deleting `stream_ts` and the two XC live patterns with the rest of
  the package would have 403'd every live tune behind nginx. They survive in
  `apps/proxy/stream_routes.py` as route declarations that exist **to be
  resolved, never to be called**: both callables log a warning and answer
  `501`, and the inline `authorize_stream` fallback that used to sit beside
  them in `live_proxy/views.py` went with the package. A deployment without
  nginx does not reach them either — the Go relay serves those routes on its
  own port, and Django answering 501 is how it says so.
- **`proxy_set_header` replaces, it does not merge.** A location that declares
  any `proxy_set_header` of its own inherits none of the server-level ones, so
  the three byte-path locations re-declare all six. Uncaught, every live
  client's `ip_address` silently becomes nginx's own address while VOD and
  catch-up — still on `uwsgi_pass`, a different directive family with
  different inheritance — keep reporting correctly. `^~ /proxy/relay/`
  deliberately re-declares none.
- **A `proxy_pass` location inherits simple server-level directives that its
  `uwsgi_pass` predecessor never saw.** `proxy_connect_timeout` was set at
  server level for an unrelated `proxy_pass` elsewhere in the same block; the
  flipped locations picked it up silently and exceeded the modular role
  split's 70s budget. All four now set it explicitly. The general rule: when a
  location changes directive family, audit the *server* block for the new
  family, not only the location.
- **Buffering is a per-family decision.** `proxy_buffering off` on the three
  Go-bound byte paths, `uwsgi_buffering off` on the six still speaking uWSGI,
  and nothing on `^~ /proxy/relay/`, which serves short JSON. The historical
  bug was the mirror image of the new hazard — `proxy_buffering off` written
  against a `uwsgi_pass` location, where it is inert and nginx spools live TS
  to disk.
- **Redis is still in the deployment and still shares DB 0**, but the video is
  out of it. What remains on the **byte** path is nothing; a live tune still touches
  the provider-slot counters and Django's own assignment keys, but from the
  control plane rather than from the relay. What remains overall is
  the provider-slot counters, the VOD and catch-up halves of the per-user
  connection scan, Django's own assignment keys, and Celery/Channels/cache.
  Phase 3's remaining scope is smaller than its charter describes.
- **`-race` becomes load-bearing for the first time.** The Python relay's 18
  `threading.Thread`s — non-test, inside `live_proxy/`, out of 27 across the
  whole of `apps/proxy/` — were greenlets on one OS thread, where a data race
  was structurally impossible. Goroutines are not, so `go test -race` is in the
  edit hook, the commit gate and CI with no per-package exemption.
- **Zero ORM reads on the live path is now structural rather than asserted.**
  Gate 1 lived entirely inside the deleted package — `test_zero_orm_reads.py`
  and `zero_orm_allowlist.py` carried both its halves, the AST scan and the
  runtime SQL record — so it was retired with the package rather than half of
  it surviving; a binary that links no Postgres driver cannot read the ORM. What was
  lost is the part that was never about the relay: the scanner's scope-2 walk
  also ratcheted four surviving Django modules, and `apps/proxy/config.py`
  carried five of its twelve edges while ending up in neither gate. Recorded
  as a gap, deliberately not replaced in Phase 2.
