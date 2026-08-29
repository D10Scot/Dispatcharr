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
(output, M3U, EPG, XC, HDHR, timeshift, live_proxy) apply it unconditionally,
but `/api/channels/channels/` only scopes by profile when the caller passes
`?channel_profile_id=` (`apps/channels/api_views.py:1000-1017`) — a plain
`GET` there returns every channel at the requester's level regardless of
profile membership. A test asserting "user in profile X sees only X's
channels" against that endpoint needs the query param; without it, expecting
a scoped result is asserting a bug, not the product.

## Owner / follower

For a live channel, exactly one uWSGI worker holds the ownership lease and
talks upstream; every other worker is a **follower**, serving its own
clients from shared state and asking the owner to act.

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
