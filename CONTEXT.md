# Glossary

Canonical vocabulary for this codebase. Use these terms verbatim in code,
test names, issue titles and commit messages.

## Profiles — three different things

Never write a bare "profile".

- **Stream Profile** — how Dispatcharr talks to the *upstream* provider.
  Three locked built-ins: Redirect, Proxy, FFmpeg. Chooses an architecture,
  not a setting.
- **Output Profile** — an optional *downstream* transcode, shared per
  (channel, profile) across the cluster.
- **Channel Profile** — an authorization grouping. Users hold an M2M
  relationship to it; it decides which channels a user may see.

## Stream

Two meanings; disambiguate every time.

- **Stream (noun, model)** — a row: one upstream URL belonging to an M3U
  account.
- **Streaming (verb)** — delivering bytes to a client.

Prefer "upstream" for the provider side and "client" for the viewer side.

## Channel

The user-facing tuner. Holds an ordered set of Streams and fails over
between them. Identified to clients by a UUID.

**A Channel UUID is a secret.** The stream endpoint is `AllowAny`.

## Owner / follower

For a live channel, exactly one uWSGI worker holds the ownership lease and
talks upstream; every other worker is a **follower**, serving its own
clients from shared state and asking the owner to act.

## User levels

Streamer (0), Standard (1), Admin (10). Authorization runs on these plus
Channel Profile membership. Django's Group and Permission tables are
vestigial — do not use them.
