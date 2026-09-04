# 2. Every E2E test declares `@contract` or `@characterization`

Date: 2026-09-01

## Status

Accepted

## Context

`CLAUDE.md` states this fork's direction: extract the streaming relay from the
Django web workers into its own process. The E2E suite — 77 spec files, 191
test declarations across eight Playwright projects — exists to be the safety
net that extraction is done against.

It cannot do that job, for one reason: **a test failure on a migration branch
is unclassifiable.**

Some of these tests assert behaviour a client can observe, and must survive any
rewrite that preserves behaviour. Others deliberately assert facts about *this*
implementation — `manage.py showmigrations` output, Redis key shapes, `pgrep -x
ffmpeg` counts, the AIO image's filesystem layout. Both kinds go red when the
relay moves. Only the first kind means something broke.

The distinction already exists de facto, in project boundaries
(`streaming-greybox`, `lifecycle`) and in prose. Neither is per test, and the
split already leaks: `tests/lifecycle/restart-persistence.spec.ts` mixes
portable assertions (rows survive a restart) with AIO-image characterization in
the same file. A migration branch reading that file learns nothing about which
half to trust.

The alternatives were: separate directories per kind (a large move, and it
cannot express a file that legitimately contains both); a naming convention in
test titles (breaks on rewording, and unenforceable); or a per-test tag.

## Decision

Two tags, using Playwright's native `{ tag: … }` option — structured data that
survives `--grep`, appears in the JSON reporter, and cannot be broken by
rewording a title.

- **`@contract`** — asserts behaviour observable at a client-facing surface:
  HTTP status and body, TS bytes on the wire, a row read back through the REST
  API, a rendered page. It must pass unchanged against any implementation that
  preserves behaviour. **This is the default, and it needs no justification** —
  portable is the standard this suite is held to.

- **`@characterization`** — deliberately coupled to this implementation.
  Asserts something true of the AIO image, the Redis key layout, the process
  table, the Django migration state or the container filesystem, which a correct
  reimplementation is permitted to change. **Every `@characterization` test must
  carry a comment naming the implementation fact it pins.**

That comment requirement is the point of the whole decision. Without it, a
migration branch reads N red tests and re-derives, one by one, which ones
matter. With it, the same branch reads N sentences saying exactly what moved.

**Ambiguity resolves to `@contract`**, and the asymmetry is the reason: a test
wrongly marked `@characterization` is *invisible* on a migration branch — its
failure is expected, so nobody looks. Wrongly marked `@contract`, it is a false
alarm someone reads and reclassifies. Silence in one direction, noise in the
other. Noise is recoverable.

## What a migration branch does with each

- A red **`@contract`** test blocks. Behaviour changed; either fix the
  implementation or argue the test was wrong.
- A red **`@characterization`** test is read, not fixed. Its comment says what
  it pinned; the branch decides whether to update the assertion to the new
  implementation or delete the test because the fact it pinned no longer
  exists. "Making it pass" is usually the wrong response.

## Enforcement

`e2e/tests/guards/tags.spec.ts`, in the `guards` Playwright project. It parses
every spec with the TypeScript compiler API and requires exactly one of the two
tags on every test declaration — directly, or inherited from an enclosing
`test.describe`.

It fails closed. A declaration whose shape the checker cannot read — a details
object passed by reference, an unrecognised `test.*` form — is reported
`unverifiable` and fails, unless pinned in `KNOWN_UNVERIFIABLE` with a written
reason. That discipline is inherited from
`e2e/tests/guards/pageerrors-enforcement.spec.ts`, whose header records why: a
checker that silently skips a shape it cannot read has the same blind spot,
with the same consequence, as the gap it was written to close.

The guard shipped in warning mode for exactly one pull request, so the retag
could land as its own reviewable diff, then flipped to blocking. The
unverifiable check never waited on that flip — a hole in the checker is not a
retag task.

## Consequences

- Every new test picks a side. `e2e/README.md`'s "Writing a test" carries the
  rule; the guard enforces it.
- Goals G12–G15 tag their own tests as they add them, rather than a second
  retag later.
- Anything on a `tests/guards/allowlist.ts` capability list is normally
  `@characterization` — those are the calls that stop meaning anything once
  the relay is its own process. The one exception documents itself in-file:
  `tests/streaming-greybox/nginx-stream-buffering.spec.ts` is `SUBPROCESS`-listed
  for its `docker exec ... nginx -T` mechanism but tagged `@contract`, because
  what it pins (the `uwsgi_buffering` directive) is a load-bearing deploy
  fact meant to survive the split, not an artifact of the current
  single-process shape.
- **A third tag is out of scope.** `@slow`, `@flaky` and per-area tags were
  considered and rejected: two tags with a stated default is a contract, and
  more tags is a taxonomy nobody maintains. The guard rejects any test carrying
  both of the two it knows, and ignores unrelated tags only insofar as exactly
  one of the two must still be present.
