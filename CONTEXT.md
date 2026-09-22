# Glossary

Canonical vocabulary for this codebase. Use these terms verbatim in code,
test names, issue titles and commit messages.

## Profiles — three different things

Never write a bare "profile".

- **Stream Profile** — how Dispatcharr talks to the *upstream* provider.
  Chooses an architecture, not a setting: Redirect, Proxy, or subprocess.
  Five locked rows ship, not three — `ffmpeg`, `streamlink` and `VLC` are
  three spellings of the subprocess architecture, alongside `Proxy` and
  `Redirect`. A test working against `/api/core/streamprofiles/` should
  expect all five to exist, by name, rather than asserting how many rows
  come back — a bare count is exactly the kind of assertion this harness's
  own rule (never assert a global count) exists to rule out, and it takes
  only a sixth locked profile shipping to turn a count assertion into a
  flake.
- **Output Profile** — an optional *downstream* transcode, shared per
  (channel, profile) across the cluster.
- **Channel Profile** — an authorization grouping via M2M membership, but
  membership is opt-in restriction, not opt-in access: a user with *zero*
  Channel Profiles gets **unrestricted** access to every channel at or below
  their user level, not none. Profiles only narrow access once at least one
  is assigned. Don't assume a freshly seeded user with no profiles sees
  nothing.

## Stream

Two meanings; disambiguate every time.

- **Stream (noun, model)** — a row: one upstream URL, usually belonging to
  an M3U account. `Stream.m3u_account` is nullable — a user-created Stream
  (`Stream.is_custom`) belongs to no account.
- **Streaming (verb)** — delivering bytes to a client.

Prefer "upstream" for the provider side and "client" for the viewer side.

## Channel

The user-facing tuner. Holds an ordered set of Streams and fails over
between them. Identified to clients by a UUID.

**A Channel UUID is a secret.** The stream endpoint is `AllowAny`.

The authorization gate is **per-channel**, not a single global capability:
each `Channel` carries its own `user_level` (`apps/channels/models.py:357`).
The `user_level__lte=<requester's level>` filter is applied broadly across
listing endpoints (`apps/output/views.py:139-145`, and
`apps/channels/api_views.py:1044-1045` for the `/api/channels/channels/`
REST list itself). The Channel Profile membership half of the gate (see
above) is **not** universal, though: the client-facing output surfaces
(output, M3U, EPG, XC, HDHR, timeshift, and the live tune path through the
authorize hop) apply it unconditionally,
but `/api/channels/channels/` only scopes by profile when the caller passes
`?channel_profile_id=` (`apps/channels/api_views.py:1000-1017`) — a plain
`GET` there returns every channel at the requester's level regardless of
profile membership. A test asserting "user in profile X sees only X's
channels" against that endpoint needs the query param; without it, expecting
a scoped result is asserting a bug, not the product.

## Owner / follower

**Not a live-path term any more, and the words are still in use, so say
which one you mean.** Until Phase 2 stage 2d-4, exactly one uWSGI worker
held a live channel's ownership lease and talked upstream while every
other worker was a **follower**, serving its own clients from shared
Redis state and asking the owner to act. The Go relay is one process
holding one in-memory registry, so a live channel has no owner election,
no lease and no followers (ADR 0006).

Two surviving mechanisms still use the words, for different things:

- **VOD session ownership** — `RedisBackedVODConnection` records which
  worker holds a session and transfers it on a later request
  (`apps/proxy/vod_proxy/multi_worker_connection_manager.py`). A lock,
  not an election, and per session rather than per channel.
- **Chunk-cache follower** — one worker builds a cached chunk and
  concurrent **followers** replay it from Redis rather than rebuilding
  (`apps/output/streaming_chunk_cache.py`). Unrelated to either of the
  above.

## Upstream provider

The fake IPTV source the E2E suite controls, standing in for a real provider
in tests. Distinct from an **M3U Account**, which is Dispatcharr's own record
of a provider, and from a **Stream**, which is one playable URL — a single
upstream provider serves a whole catalogue of streams.

## Scenario

One test's isolated view of the upstream provider: its own catalogue,
credentials, connection limit and faults, addressed by an id in the URL
path. Not a session; not a Playwright project.

## Fault

A deliberate misbehaviour the upstream provider is switched into to drive a
Dispatcharr failure path. Distinct from a bug: a fault is expected, and the
product is expected to survive it.

## Category

An Xtream Codes grouping, ingested from an XC provider's `get_live_categories`/
`get_vod_categories`/`get_series_categories`. Never a "profile" — see Profiles, above, for the three
things that word already means in this codebase. A live category becomes a **Channel Group**; a VOD
or series category becomes a **VOD Category** (`VODCategory`, `apps/vod/models.py`, unique on
`(name, category_type)` **globally**, not per account — two accounts declaring the same category
name share one row).

## Catch-up / timeshift

One feature, two names, used interchangeably by the product itself: `apps/timeshift/` is the app
that serves `/proxy/catchup/`. Prefer **catch-up** when naming the feature in prose, test names and
issue titles; use **timeshift** only when naming a symbol that already spells it that way
(`apps/timeshift/`, `TimeshiftRedisKeys`, `client_timeshift_url_layout`, and so on) — don't rename
those, and don't introduce a new symbol spelled "catchup"/"catch_up" where an existing convention
already says "timeshift".

## User levels

Streamer (0), Standard User (1), Admin (10) — model labels, verbatim
(`apps/accounts/models.py:21`). Authorization runs on these plus Channel
Profile membership (see Channel Profile, above — zero profiles means
unrestricted, not none). Django's Group and Permission tables are
vestigial — do not use them.

## Programme terms

- **Phase 0** — "harden in place": the work that makes the relay extraction
  safer without moving any boundary. Exactly five items: the two CI
  label-routing defects, `npm ci` in the image build, a release that cannot
  ship an untested commit, the Main ruleset requiring every test aggregate,
  and provider credentials no longer logged. Deployment defaults (published
  Postgres port, wildcard hosts/CORS/CSRF, plaintext XC passwords, no request
  timeout) are **not** Phase 0 — they are recorded as constraints the
  extracted relay must not recreate.
- **Migration gate** — the set of required checks a PR to `main` must pass:
  the E2E, Lifecycle, Backend and Frontend result aggregates. A `migration/**`
  branch runs the gate in full mode (every project, both bash suites). "Green
  CI" without the gate is not evidence.
- **Result aggregate** — the one job per test workflow that a ruleset can
  require. It always reports: it passes when the workflow's own change
  detection proved the suite unnecessary, and otherwise only when every heavy
  job succeeded. A skipped heavy job on a required run is a failure, not a pass.
- **Phase 1** — "still Python": the process split, described in
  `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`. Five
  steps that move no relay internals: process split with a supervisor and
  roles, an authorize hop keyed by relay name, next-source and events calls
  to Django, a relay status/control API, and the tune-path tests and lifted
  constraints that gate everything after. Stopping after Phase 1 — or after
  step 1 or step 4, its two legitimate stopping points — is not a failure of
  the plan; widening it while it is in flight is.
- **Phase 2** — "optionally Go": the live byte path reimplemented as a
  stdlib-only Go binary, described in
  `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`. Four
  stages: 2a built the coverage and the parity matrix over the Python
  implementation, 2b closed the two gates, 2c wrote the Go relay one
  behaviour at a time against that matrix, and 2d cut over — nginx flipped
  in 2d-3, `apps/proxy/live_proxy/` deleted in 2d-4. Complete. The Python
  relay process stays, narrowed to VOD and catch-up.
- **Phase 3** — "remove Redis from the data path": not started, and
  smaller than its charter describes, because Phase 2's move to
  in-process state already took the live ring buffer, the ownership leases
  and the client sets out of Redis. What is left is VOD, catch-up and the
  provider-slot counters.
- **Parity matrix** — `docs/relay-parity-matrix.md`: one row per
  externally-observable live-path behaviour, each carrying the source it
  was derived from and the test that pins it. Rows are addressed by number
  and an id is never reused or renumbered; a retired row keeps its id and
  says so. It is what made a hard cutover evidence-backed rather than
  hopeful, and it is enforced by a guard test in the `guards` Playwright
  project.
- **Relay (data plane)** — the tier that owns the byte path. Since Phase 2 it
  is **two processes in two languages**, and "the relay" without a
  qualifier is ambiguous: say **Go relay** or **Python relay**.
  - **Go relay** (`relay/`, `relay-go`, port 5658) — live TS and fMP4 and
    the XC live roots, plus the five `/proxy/relay/…` control routes.
    Stdlib-only, links no Postgres or Redis driver, keeps its channel and
    client state in process memory (ADR 0006), and reads nothing from either
    store: everything it needs arrives on the `next-source` answer.
  - **Python relay** (`docker/uwsgi.relay.ini`, `relay-uwsgi`, port 5657) —
    VOD, catch-up and `timeshift.php`. Same Django code and the same URL
    config as the API process, a second uWSGI with a request timeout
    deliberately left off. It still *reads* PostgreSQL: VOD and catch-up
    resolve their content at tune time. It performs no ORM writes.
  Neither resolves a user or authorizes anything itself — that is the
  authorize hop's, below.
- **Control plane** — the process (or processes) that decide things: the API,
  the UI, Xtream JSON, HDHR, Celery, Daphne. Owns every durable decision —
  who may stream, which source a channel uses next, whether a provider slot
  is free — and answers the relay's questions over HTTP rather than sharing
  Python memory with it. Some coordination stays in Redis by design: the
  provider-slot counters, and the timeshift and VOD halves of the per-user
  connection scan, are written by control-plane code rather than by the relay,
  so they are not relay-private state and never moved behind the control API.
  The live half of that same scan did move, in Phase 1, and then stopped
  existing: the Go relay's client registry is a map in its own memory and
  `GET /proxy/relay/channels?clients=all` is the only way to read it.
- **Role** — the value of `DISPATCHARR_ROLE` (`all`, `api`, `relay`,
  `worker`) that tells supervisord which programs to start in a given
  container. `all` is the AIO default; `api`/`relay`/`worker` are the modular
  split. Same image, same settings, same urlconf in every role — what differs
  is which programs run, and whether nginx runs at all: the `api` and `all`
  roles run it with the full location table, and `relay` and `worker` run
  none. The supervisord config is picked from the role together with
  `DISPATCHARR_ENV` and `DISPATCHARR_DEBUG`, because `dev` runs vite in place
  of nginx and `debug` runs a different uWSGI ini — the same three-input
  ladder the entrypoint already uses to choose that ini.
- **Authorize hop** — the nginx `auth_request` subrequest Django answers once
  per tune, before the relay ever sees the connection. Applies the `STREAMS`
  network ACL, resolves the principal, checks `user_level`, channel-profile
  membership, `hidden_from_output` and the user's `hide_adult_content`
  against `Channel.is_adult`, and resolves the Output Profile — every stream
  surface through one function. An administrator bypasses every channel check
  but not the ACL or the per-user stream limit, which is what the admin UI's
  own preview player relies on. See ADR 0005.
- **Relay name** — the header (`X-Relay-Name`, default `py`) Django's
  authorize response carries and nginx's `map` turns into an upstream group
  name. It is a name rather than a Python-or-Go flag on purpose, and it
  remains the scale-out seam — but Phase 2 did **not** use it as a canary
  switch and could not have: `$relay_name` comes from one process-wide
  `settings.RELAY_DEFAULT_NAME`, so the map can say "this deployment's
  relay is X" and cannot say "these four locations resolve differently
  than those six" (nginx.conf's own comment says five; measured, it is
  four `proxy_pass http://relay_go` against six `uwsgi_pass
  $relay_upstream`). The four Go-bound locations name `relay_go` literally
  and consult no map. See ADR 0005 for the mechanism and ADR 0006 for why
  the cutover was hard instead.
