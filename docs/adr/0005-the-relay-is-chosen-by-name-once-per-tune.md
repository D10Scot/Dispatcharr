# 5. The relay is chosen by name once per tune

Date: 2026-09-04

## Status

Accepted

## Context

*Splitting the Planes* (the original extraction proposal) put a short-lived,
HMAC-signed URL on the relay's stream endpoint: Django would mint a token per
session and the relay would validate it statelessly, with no per-request call
back to Django. Phase 0's carried-constraints table repeated that design
verbatim as the fix for `stream_ts` being `AllowAny` behind nothing but a
`STREAMS` network ACL defaulting to `0.0.0.0/0`.

Writing the Phase 1 spec, three points contradict that design:

- **Playlists cache the URL for days.** M3U, the HDHomeRun lineup and Xtream
  `get.php` all embed `/proxy/ts/stream/<uuid>` (and the XC root forms) as a
  durable link a client is expected to reuse indefinitely. A signed URL with
  any useful expiry either breaks that reuse or is too long-lived to be worth
  signing.
- **The channel UUID shape is the product's public contract**, referenced by
  every player, DVR client and third-party integration that has ever pointed
  at this server. Changing the URL shape to carry a token is a breaking change
  Phase 1 has no reason to make.
- **Two other defects sit on the same code path.** `stream_xc`, `stream_vod`
  and `catchup_proxy` each resolve a user and apply authorization inline, and
  `hide_adult_content` is enforced in listing views but not in
  `live_proxy/views.py` or `timeshift/views.py` (issue #87 live, #95 catch-up)
  — a hidden or adult channel is unlistable but streamable by UUID. A signed
  URL fixes none of this; it only adds a token to a check that still runs, or
  doesn't run, exactly as it does today.

Three shapes for the authorization hop were considered:

1. **Signed URL per playlist entry** (the original proposal). Rejected for
   the caching reason above: Django would have to mint a token with no
   expiry to survive a cached playlist, which is not a meaningful signature.
2. **No authorization change** — leave `stream_ts` as `AllowAny`, gated only
   by the network ACL, and let the process split alone carry Phase 1. Rejected
   because it ships the extraction without closing #87/#95, and because a
   relay process that resolves users and queries `PostgreSQL` to authorize is
   exactly the coupling Phase 1 exists to remove.
3. **An authorization subrequest, once per tune** — nginx's `auth_request` to
   Django before proxying to the relay, with an inline fallback in the stream
   views for deployments without nginx (dev `runserver`). Accepted.

A second, related question: where do provider slots live? The original
proposal moved the candidate-stream list and `max_streams` enforcement into
the relay, on the reasoning that failover needs to be fast and local. Research
into `apps/m3u/connection_pool.py` found the slot counter (`profile_connections:{id}`)
is shared by three consumers — live, VOD and catch-up — and VOD/catch-up
already do reservation from Django-side stateless request handlers, not from
a relay. A live-only relay cannot own a counter three surfaces share, and a
candidate list snapshotted at channel start goes stale the moment a VOD
session takes the same profile's last slot.

## Decision

**Authorization is Django's decision, made once per tune, never per byte.**

On every tune, nginx issues an `auth_request` subrequest to Django
(`apps/proxy/authorize.py`'s `authorize_stream`, exposed at an `internal`
location). Django applies the `STREAMS` network ACL, resolves the principal
(the union of what `stream_ts`, `stream_xc`, `stream_vod` and `catchup_proxy`
already accept: Xtream credentials, JWT, API key, query-param JWT, session or
anonymous), `user_level`, channel-profile membership, `hidden_from_output`,
the user's `hide_adult_content` against `Channel.is_adult`, Output Profile
resolution and the per-user
`stream_limit`, and answers 200 with headers or 401/403/404/429. nginx copies
the 200 response's headers into nginx variables with `auth_request_set` — the
only context where the subrequest's own response headers are readable — and
re-emits them toward the relay as `uwsgi_param HTTP_X_RELAY_*` values. The
relay never resolves a user or queries PostgreSQL to authorize.

A client cannot forge that trust, in two layers. The marker header
`X-Dispatcharr-Authorized` carries an HMAC of `SECRET_KEY`, not a literal
flag, so producing it requires the deployment's own key — which matters
because "only nginx can reach the relay" is not true in every shape: uWSGI's
HTTP listener is published in dev and debug, and the relay's port is
reachable from anywhere on a compose network. On top of that, since nginx
0.8.40 a `*_param` whose name begins with `HTTP_` overrides the same-named
client header, so in relay-bound locations nginx's own values replace
whatever the client sent, and every other Django-bound location blanks the
same five params through one shared include — necessary because the relay
and the API run the same URL configuration and either can serve a stream
view.

Deployments without nginx (dev `runserver`) fall back to the same function
called inline from the stream views, so the two paths cannot drift.

The DVR is authorized as an internal principal rather than as an anonymous
one. It fetches the same `/proxy/ts/stream/<uuid>` URL through ffmpeg with no
credential, so once that route sits behind the hop it would fail on any
hidden, adult or profile-gated channel. It carries the shared internal HMAC
header instead, which bypasses the per-user checks and still resolves the
Output Profile.

One of the response headers is `X-Relay-Name`, not a Python/Go flag and not a
boolean. In Phase 1 there is one relay and the header always reads `py`, from
a single `settings.RELAY_DEFAULT_NAME`. It exists because Django, not the
relay, is where "which backend serves this channel" has to be decided: nginx
copies the header into `$relay_name` with `auth_request_set` and a `map`
turns that into an upstream *group* name, with one entry today. Phase 2's
canary (a Go relay taking a subset of channels) and any later scale-out both
become a second map entry, a second `upstream` block and a row in a Django
assignment table, not a code change on either side. The map values are group
names rather than literal addresses because nginx resolves a variable
address through a `resolver` when it is not a declared group, which a compose
service name would fail without.

**Slots stay in Django.** `Channel.get_stream()` — selection and reservation
together — keeps its current shape and callers. The relay's only
failover-time dependency on Django becomes one HTTP call
(`POST /api/relay/channels/<uuid>/next-source`), with a degraded,
logged-and-unenforced fallback to a cached candidate list when Django is
unreachable. The relay never enforces `max_streams`; it asks.

## Consequences

- Every stream surface — live TS/fMP4, VOD, catch-up, and the six XC root
  forms — authorizes through the same function, so #87 and #95 close in one
  place instead of three.
- An administrator keeps the bypass they have today. `_user_can_access_channel`
  already lets `user_level >= ADMIN` past every channel check, and the admin
  UI's own preview player depends on it; `authorize_stream` generalises that
  bypass rather than inventing one, and it stops at the network ACL and the
  per-user stream limit.
- One surface has no channel at all: `/proxy/ts/stream/<stream_hash>` serves a
  raw `Stream` for the admin UI's single-stream preview. It keeps exactly
  today's behaviour — the ACL and the stream limit apply, no channel check
  does — because there is no channel to apply one to.
- A new tune needs Django up; an existing stream does not, because
  authorization happens once at connect time and the relay holds no
  per-request dependency on Django after that.
- Deployments without nginx (dev `runserver`) need the inline fallback path,
  which duplicates no logic — it calls `authorize_stream` directly.
- The relay stops *resolving* a principal or an Output Profile: which user,
  and which profile, are Django's answers, carried in `X-Relay-User` and
  `X-Relay-Output`. It still reads both rows by primary key — `add_client`
  stores the `User`, and `OutputProfile.build_command()` is model behaviour
  a header cannot carry — so the tune-time ORM reads fall from a resolution
  chain to two indexed lookups rather than to zero. `M3UAccount`'s
  tune-time reads move behind the next-source call in PR 6, not here.
- A channel marked `hidden_from_output` stops being streamable by UUID even
  anonymously, because that field is a property of the channel and needs no
  principal. `hide_adult_content` is a per-user preference read against
  `Channel.is_adult`, and remains inapplicable to
  an anonymous request rather than skipped — the same distinction the
  HDHomeRun surface forces, and the reason that surface needs a different
  fix rather than this one.
- Every internal hop — relay to Django, Django to relay, the DVR to the
  relay, and nginx's trust marker — is authenticated by an HMAC of
  `SECRET_KEY`, compared with `hmac.compare_digest`, under two distinct
  context strings so a leaked marker cannot be replayed as an internal
  principal. None of it needs provisioning, but only because every role reads
  the same `/data/jwt` file — which makes the shared `/data` volume a
  correctness requirement of the deployment, not a convenience.
- The canary switch and horizontal scale-out Phase 2 and later phases need
  already exist as of Phase 1: a header naming a relay, and a Django-side
  mapping from channel to name. Building the general mechanism now, for a
  single fixed value, costs one `map` block and one settings entry.
- The channel UUID remains the public, cacheable identifier; nothing in the
  URL shape changes. The relay's stream endpoint is not the Django-minted
  signed URL Phase 0's carried-constraints table described — that row is
  reworded (see the Phase 1 spec's Requirements table) to describe the
  authorize hop instead.
- Provider-slot accounting is unaffected by which relay serves a channel:
  because Django still owns `reserve_profile_slot`/`release_profile_slot`,
  adding a second relay (Phase 2) or a second live surface never requires
  teaching the relay about a counter it does not own.
