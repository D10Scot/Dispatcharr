# Glossary

Canonical vocabulary for this codebase. Use these terms verbatim in code,
test names, issue titles and commit messages.

## Profiles — three different things

Never write a bare "profile".

- **Stream Profile** — how Dispatcharr talks to the *upstream* provider.
  Chooses an architecture, not a setting: Redirect, Proxy, or subprocess.
  Five locked rows ship, not three — `ffmpeg`, `streamlink` and `VLC` are
  three spellings of the subprocess architecture, alongside `Proxy` and
  `Redirect`. A test enumerating `/api/core/streamprofiles/` should expect
  five locked rows.
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
each `Channel` carries its own `user_level` (`apps/channels/models.py:357`),
and listing endpoints filter with `user_level__lte=<requester's level>`
(e.g. `apps/output/views.py:139-145`) — plus Channel Profile membership, see
above.

## Owner / follower

For a live channel, exactly one uWSGI worker holds the ownership lease and
talks upstream; every other worker is a **follower**, serving its own
clients from shared state and asking the owner to act.

## User levels

Streamer (0), Standard User (1), Admin (10) — model labels, verbatim
(`apps/accounts/models.py:21`). Authorization runs on these plus Channel
Profile membership (see Channel Profile, above — zero profiles means
unrestricted, not none). Django's Group and Permission tables are
vestigial — do not use them.
