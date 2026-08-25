# 1. E2E tests run against a shared, API-seeded AIO container

Date: 2026-08-23

## Status

Accepted

## Context

E2E tests need a running Dispatcharr. The AIO image takes 40–60 seconds to
become ready and is ~3.6 GB. A suite that boots a container per spec file
would cost more in startup than in testing.

The alternatives were: a fresh container per spec file (total isolation,
unaffordable); a shared container with a test-only database reset endpoint
(fast and isolated, but ships new surface area in production code); or a
shared container seeded through the existing REST API.

## Decision

One container per CI job. Tests seed what they need through the REST API and
assert only on entities they created, which carry a generated name prefixed
`e2e-w{worker index}-` (tests assert the pattern as `/^e2e-w\d+-/`).

Populations that genuinely cannot share an instance — first-run setup, global
settings, migrations, PUID/PGID, TLS Postgres — run in a separate `pristine`
project against their own container.

## Consequences

- No test may assert on a global count or an unfiltered list. The instance is
  never empty. This is the constraint that most often bites: it broke one of
  this harness's own exemplars during implementation — a smoke test asserted
  on the "Create Channel" empty-state onboarding button, which stops
  rendering the moment any channel exists, and the suite's own seeding put
  one there (`e2e/tests/seeded/authenticated-session.spec.ts`, fixed in
  commit `f9c6fe52`).
- Seed helpers generate names and refuse caller-supplied ones — not merely by
  convention, but enforced at runtime: each factory in `e2e/fixtures/seed.ts`
  spreads the generated identity field (`name`, or `username` for `user`)
  *after* `...overrides`, so a caller-supplied value is silently overwritten
  rather than accepted. That rule is pinned by committed tests
  (`e2e/tests/seeded/seed-fixture.spec.ts`), not left to reviewer memory.
- Generated names carry per-`Seeder` entropy (a random `runToken`, distinct
  from the deterministic worker index and test ID) specifically so re-running
  a suite against a live, non-reset container cannot collide with rows its
  own previous run left behind — `testId` and `workerIndex` alone are stable
  across repeat invocations of the same spec and would otherwise regenerate
  identical names every time.
- The shared instance means no test may assume it is empty, full stop — the
  onboarding-button failure above is the general case, not a one-off.
- No cleanup: the container is destroyed with the job, and cascade-delete
  ordering across Channel/Stream/ChannelProfile is a flake source that masks
  real assertions.
- One shared instance behind one IP address means the whole suite shares the
  login endpoint's rate limit (`POST /api/accounts/token/`, 3/minute) — a
  direct consequence of sharing an instance, not an independent design
  choice. See `e2e/README.md`'s login throttle section for the numbers and
  the trap it sets for a naive multi-principal test.
- Anything needing a pristine instance must go to the `pristine` project. That
  project is not optional overhead; it is where those tests live.
- Reversing this later means rewriting every assertion that filters by prefix.
