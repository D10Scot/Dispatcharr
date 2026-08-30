# E2E Tests

Playwright against a real Dispatcharr AIO container.

## Quick start

```bash
./scripts/e2e_up.sh --reset     # fresh container; reuses the existing image
cd e2e
npm ci
npx playwright install --with-deps chromium
npm run typecheck && npm run test:seeded
```

`--reset` destroys the container and its data volume, but only *builds* the
image if `dispatcharr-e2e:local` doesn't already exist. If you changed product
code and want to test it, remove the stale image first:
`docker rmi dispatcharr-e2e:local`.

## Container lifecycle

The container outlives the test run — that is what makes a second
`npm run test:seeded` cheap. It is not self-cleaning, so stop it when you are
done:

| Command | Effect |
|---|---|
| `./scripts/e2e_up.sh` | Start, reusing an existing container and its data |
| `./scripts/e2e_up.sh --stop` | Stop it, keep the container and the volume. Start again to resume with the same superuser and seeded rows |
| `./scripts/e2e_up.sh --reset` | Destroy container + volume, then start fresh |
| `./scripts/e2e_up.sh --recreate` | Replace the container, keeping the volume, network and provider. The one mode that expresses an upgrade: honours `DISPATCHARR_E2E_IMAGE`, so setting it and re-running actually serves the new image, unlike every mode above |
| `./scripts/e2e_up.sh --down` | Destroy container + volume, start nothing |

`DISPATCHARR_E2E_PORT`, `_CONTAINER`, `_VOLUME` and `_IMAGE` override the
defaults, and every command above respects them. The equivalent
`DISPATCHARR_E2E_UPSTREAM_CONTAINER`/`_PORT` variables exist for the fake
upstream provider but are **not safe to change**: unlike the variables
above, nothing downstream of `scripts/e2e_up.sh` reads them back — the
provider's own default origin, the `upstream` fixture's base URLs, and its
DNS-failure detection all hardcode `e2e-upstream` and `9402`. Overriding
either starts a working container under a name or port the suite can no
longer find.

**The container is published on `127.0.0.1` only.** Once bootstrap has run it
holds a superuser whose password is committed to this repository in plain
text, so it must not be reachable from the LAN — a peer on your network would
otherwise have an admin account on it. A container created *before* this was
the case keeps its old binding: `--down`, then start again, to pick the new
one up. CI binds the same way.

## Projects

| Project | What it is for |
|---|---|
| `bootstrap` | Creates the superuser, pre-warms the `IntervalSchedule` row (see below) and writes auth state. Runs automatically as a dependency of `seeded`, `streaming`, `streaming-failover` and `streaming-greybox` — every project except `pristine` and the two `lifecycle` ones, which each need an instance bootstrap has not touched |
| `pristine` | Needs an instance with **no superuser**: first-run setup, and global `CoreSettings` changes |
| `seeded` | The default. Shared instance, parallel workers, API-seeded data |
| `streaming` | Byte-level tests. Long timeouts, fewer workers |
| `streaming-failover` | Failover behaviour: dead-air and buffering watchdogs. Long timeouts, fewer workers |
| `streaming-greybox` | Tests that reach past the API into Redis or the container directly (e.g. counting live `ffmpeg` processes). Long timeouts, one worker — **must be run alone locally**: in CI each matrix job gets its own container, but locally all projects can share one, and this project observes container-wide state that whatever else is running would disturb |
| `lifecycle` | Restarts the container mid-test. **Runs alone** — it destroys the container every other project shares. No `bootstrap` dependency: it provisions its own admin |
| `lifecycle-upgrade` | Boots a published baseline image, seeds, then replaces the container with the local build on the same volume. **Runs alone.** Runs in `lifecycle-tests.yml`, not in `e2e-tests.yml`'s matrix |

`streaming` runs at `workers: 2` — its byte-level reads are slow but do not
touch anything another test in the same project could observe.
`streaming-failover` and `streaming-greybox` both pin `workers: 1` instead,
each for its own container-wide hazard: `failover-buffering.spec.ts` mutates
the global `proxy_settings` row for the duration of its run, and
`output-profile-sharing.spec.ts` counts every `ffmpeg` process running in the
container (`pgrep -x ffmpeg`) via `greyboxRedis()`. Neither observable is
scoped to its own channel, so a second worker running anything else in the
same project would race it — see each project's `workers` comment in
`playwright.config.ts` for the full reasoning. A future grey-box test that
mutates Redis directly, the way the deleted ownership-lease flagship did (see
`COVERAGE.md`), would be the same class of risk in `streaming-greybox`, which
is why that project doesn't trust every future test to be independently safe
at higher concurrency either.

**The set of specs allowed to reach for grey-box Redis access is a checked
allowlist, not a comment asking politely.** `e2e/fixtures/greybox/redis.ts`
exports `GREYBOX_ALLOWLIST`, and
`e2e/tests/streaming-greybox/quarantine.spec.ts` walks every `.ts` file under
`e2e/`, greps each for an import of `greybox/redis`, and asserts the set it
finds matches the allowlist exactly — in either direction: a new grey-box
import that isn't listed fails the meta-test, and a stale allowlist entry for
a file that no longer imports it fails the same way. That is what happened
when G4's ownership-lease flagship (`ownership-lease.spec.ts`) was deleted as
an unprovable gap (see `COVERAGE.md`'s Streaming/G4 rows) — its allowlist
entry had to go with it, or `quarantine.spec.ts` would fail on a name that no
longer exists. A convention written down in this file would rot silently the
same way; this one fails CI instead.

`pristine` deliberately has no `bootstrap` dependency — it needs the
superuser *not* to exist yet, which is the entire point of that project, and
is why `pristine` and `seeded` cannot share a container. `bootstrap` consumes
the first-run state, so run them separately, resetting between:

```bash
./scripts/e2e_up.sh --reset && npm run test:pristine
./scripts/e2e_up.sh --reset && npm run test:seeded
```

**`pristine` is not the home for every test that cannot use `seeded`.** Its
requirement is narrow and specific — no superuser yet — and that is the whole
of it. Upgrade-with-migrations, restart persistence, PUID/PGID and TLS Postgres
need instances that are *differently configured*, not merely fresh: a previous
image, a different launch environment, and different services and volume
history respectively. None of them shares a container with `pristine`, or with
each other. `docker/tests/test-puid-pgid.sh` drives 20 scenarios through its
own `docker run` orchestration, standing up a container and a volume per
scenario; `test-tls-postgres.sh` stands up its own PostgreSQL and Redis with
generated certificates on a dedicated network. Those are G7's
scenario-specific jobs, not `pristine` specs — see the G7 paragraph in
`docs/superpowers/specs/2026-08-23-e2e-coverage-roadmap-design.md`, which is
the authority here. Both suites leak a PostgreSQL volume per scenario on
every run, tracked as
[D10Scot/Dispatcharr#41](https://github.com/D10Scot/Dispatcharr/issues/41);
neither suite is modified by this harness, so the cleanup lives with that
issue, not here.

`lifecycle` and `lifecycle-upgrade` go further than needing a differently
configured instance: they **destroy** it. Both import
`e2e/fixtures/instance.ts`, which stops, replaces or removes the shared
container outright, and `scripts/e2e_up.sh`'s `destroy()` takes the shared
Docker network and the `e2e-upstream` provider container down with it — see
that file's header for the full reasoning. A lifecycle spec running beside
any other project would not merely disturb it, it would delete the instance
out from under it mid-assertion, with the failure surfacing in whichever
project lost its container. That is why both run alone, in their own job and
their own runner in CI, and neither shares a container with the other:

```bash
./scripts/e2e_up.sh --reset && npm run test:lifecycle
npm run test:lifecycle-upgrade   # pulls a ~3.6 GB baseline; brings its own instance up and down
```

`npm test` (no suffix) deliberately fails with a message telling you to pick
one of the seven — there is no single invocation that is correct for all of
them, and a bare `npm test` in CI would silently run whichever config
happened to be first.

## Running against an existing instance

```bash
E2E_BASE_URL=http://my-box:9191 npm run test:seeded
```

`bootstrap` POSTs to `/api/accounts/initialize-superuser/`, which is IP-gated
to private/loopback addresses (`setup_ip_allowed` in `dispatcharr/utils.py`).
Against a public instance, set `DISPATCHARR_SETUP_ALLOWED_IP` on that instance
first.

> **Only ever point `E2E_BASE_URL` at a throwaway instance.** If the target
> has no superuser yet, this suite creates one — `e2e-admin`, with a password
> committed to this repository in plain text, as a permanent superuser. On a
> real deployment that is a handed-over admin account, and setting
> `DISPATCHARR_SETUP_ALLOWED_IP` is precisely what removes the product-side
> guard against it.
>
> Both paths that can create one — `bootstrap`, over the API, and the
> `pristine` browser test, through the first-run form — call
> `assertMayCreateSuperuser` from `e2e/setup/superuser-guard.ts` first. It is
> default-deny: creation proceeds only if `E2E_ALLOW_REMOTE_SUPERUSER` is
> **exactly** the string `1`, or the target is loopback. `=true`, `=yes` and
> `=0` are all refusals, and the error says so rather than repeating the
> instruction you thought you had followed. Running against an instance that
> is already set up needs no variable and is unaffected.
>
> The loopback exemption is deliberate, and it is not a claim that loopback is
> safe: `localhost:9191` can be an SSH tunnel to a real box. It is there
> because CI and every local run target loopback, and an opt-in that must be
> set on every ordinary run ends up exported in a shell profile — where it
> silently disarms the guard for the remote targets it exists to protect. The
> reasoning is written out in full at the top of `superuser-guard.ts`.

## The fake upstream provider — a second, local-only container

Tests that ingest from or stream through the fake IPTV provider
(`e2e-upstream/`, documented in `e2e-upstream/README.md`) need a **local
two-container topology**: `dispatcharr-e2e` and `e2e-upstream` on the same
user-defined Docker network, so Dispatcharr can resolve the provider by
container name. `./scripts/e2e_up.sh` builds and starts both, waits for the
provider to answer, then starts Dispatcharr.

**The `E2E_BASE_URL` escape hatch above does not extend to these tests.**
Pointing `E2E_BASE_URL` at a remote or already-running Dispatcharr instance
only replaces *that* container — it does nothing for the provider, and a
remote Dispatcharr instance has no route to a provider container running on
your laptop. Any test that uses the `upstream` fixture needs the full local
topology brought up by `scripts/e2e_up.sh`, not a bare `E2E_BASE_URL` run.

**XC scenarios (G8).** `upstream.scenario({ xc: true, username, password, ... })` declares an
Xtream Codes catalogue — categories, movies, series — on top of the same live-channel scenario
every other test uses; `e2e-upstream/README.md` documents the full field set and the fault
catalogue. `seed.xcAccount(scenario)` is the paired fixture step: it creates an `M3UAccount` with
`account_type: 'XC'`, the scenario's credentials on the model's own `username`/`password` fields
(not embedded in the URL, unlike a standard M3U account), and `server_url` set to the scenario's
**bare** `internal` origin — never `scenario.internal + scenario.credentialQuery`, because
`normalize_server_url` strips the query before the XC client ever sees it, silently discarding any
credentials appended that way. There is no separate URL-building helper for XC beyond that: the
scenario's own `internal`/`control` origins are what a test needs, exactly as for a non-XC
scenario.

Two asynchrony facts a test will otherwise be bitten by, both because XC ingest fires more
background tasks than a standard M3U refresh:

- **VOD ingest is a separate task, fired only after the M3U refresh completes.** A standard M3U
  refresh finishes once; an XC refresh that has VOD enabled additionally queues
  `apps.vod.tasks.refresh_vod_content` (`.delay()`'d from inside `apps/m3u/tasks.py`'s main refresh
  task, immediately after it records its own completion) — so `waitFor.m3uRefreshComplete` returning
  does **not** mean movies or series have landed yet. A test asserting on `Movie`/`Series` rows
  needs its own wait on that outcome, not a reuse of the M3U-refresh wait.
- **`server_info.timezone` reaches an `M3UAccountProfile` through a second, nested `.delay()`'d
  task.** The main refresh task queues `refresh_account_profiles.delay(account.id)`
  (`apps/m3u/tasks.py`) for every XC account, which — asynchronously, with a rate-limiting sleep
  between profiles — re-authenticates each active profile and merges `get_account_info()`'s
  `server_info` (timezone included) into `M3UAccountProfile.custom_properties`. That value is not
  present right after account creation or even right after the main refresh; it lands on its own
  schedule, later.

## The login throttle — read this before writing a multi-user test

`POST /api/accounts/token/` is rate-limited to **3 requests per minute per
client IP** (`dispatcharr/settings.py`'s `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`
sets `"login": "3/minute"`; enforced by `LoginRateThrottle` in
`apps/accounts/throttling.py`, whose `scope` is `"login"`, applied to
`TokenObtainPairView` in `apps/accounts/api_views.py`). The budget is shared with
Django admin login and with `POST /api/accounts/auth/login/`, which delegates
to the same view — all three go through one throttle scope.

Every run from one host is one client IP, so **the entire suite, across all
workers and across back-to-back runs, shares three logins per minute.** The
budget is fixed; the number of workers and tests is not. Any design that logs
in from a worker therefore fails at some scale, and it fails as a 429 that
reads like a flaky product bug.

**So the suite spends none.** A full `npm run test:seeded` performs **0**
`POST /api/accounts/token/` requests in steady state, whatever `workers:` is
set to. Three consecutive runs inside one minute were measured at 0 logins and
0 429s; a 16-test authorization matrix spread over 4 workers added 0 to that.
You do not have to budget anything as long as you use `asPrincipal`.

### How that works

`bootstrap` is the only phase of a run that logs in, because it is the only
phase that can: it is serial, both parallel projects list it in
`dependencies:`, and nothing is waiting on it. It provisions a fixed roster of
non-admin principals — `e2e/setup/principals.ts` — and writes their token
pairs to `playwright/.auth/principals.json` (gitignored, like `tokens.json`).
Workers read that file and never log in.

`playwright/.auth/` is kept at `0700` and everything in it at `0600`, tightened
on every write so a directory created by an older revision is repaired rather
than left at `0755`. It holds live admin JWTs — good for 30 minutes, and their
refresh tokens for a day — and once the container was bound to loopback the
only reader left to keep out was a local one, which is precisely what a file
mode addresses. `e2e/setup/auth-files.ts` is the single place that knows the
modes, and says why the `mode:` option on `mkdir`/`writeFile` is not enough on
its own.

| Path | Logins |
|---|---|
| Full run, warm (`principals.json` + `tokens.json` present) | **0** |
| More than 30 min since the last run (access tokens expired) | **0** — renewed through the *unthrottled* refresh endpoint |
| Cold: first run after `--reset`, deleted auth files, or >1 day (`SIMPLE_JWT.REFRESH_TOKEN_LIFETIME`) | **3** = 1 admin + 1 per principal, exactly the per-minute cap |
| Each `asUser()` call for a principal not in the roster | **+1**, per distinct `username:password`, *per worker* |

`TokenRefreshView` is **not** throttled (its class in `apps/accounts/api_views.py`
carries no `throttle_classes`, and `DEFAULT_THROTTLE_CLASSES` is `[]`), which
is what makes the middle row free: an access token lives 30 minutes, a refresh
token a day, so bootstrap and `ApiClient` both renew rather than re-login. One
sharp edge in that endpoint, filed as
[#12](https://github.com/D10Scot/Dispatcharr/issues/12): a refresh token naming
a *deleted* user gets a **500**, not a 401. Setup treats that as "log in
instead" and is unaffected; in a worker it surfaces as
`token refresh failed: 500`, which means `playwright/.auth/` is left over from
a container that has since been reset — delete it and run again.

The cold path sits exactly on the cap. Two things push it over: **adding a
principal**, and a principal whose **password has drifted**, which spends a
second login on the repair retry. Neither fails the run — every login
`bootstrap` makes, the admin's included, goes through
`loginWithThrottleBackoff` (`e2e/setup/login.ts`), which honours `Retry-After`
and waits the window out. That is why the `bootstrap` project's timeout is
derived from the roster size rather than being a round number. It is still a
real cost, so add a principal only when no existing one can express the case.

Two properties make a failed `bootstrap` cheap to retry, and both matter more
than they look:

- the admin pair is written to disk **before** the pre-warm and before any
  principal login, so a failure later in setup cannot discard a login already
  spent; and
- `principals.json` is rewritten after **each** principal, not once at the end.

Without those, a failure after the first login left nothing on disk, so the
retry ran cold *inside the window it had just emptied* and died on the admin
login with a bare 429 — reporting the throttle instead of whatever actually
broke. `bootstrap` keeps the global `retries` setting (1 in CI) precisely
because a retry is now warm and spends nothing; contrast `pristine`, which
pins `retries: 0` because its first attempt consumes the state its second
would need.

### What to reach for

- **Acting as a non-admin: `asPrincipal('streamer' | 'standard')`.** Free, at
  any scale. `PRINCIPALS` (exported from `../../fixtures`) carries their
  usernames and levels — assert against it rather than repeating literals.
  Streamer is `user_level` 0 and Standard is 1; admin is the bootstrap
  account.
- **A user row to create, mutate, assert on or delete: `seed.user()`.**
  Creating users is an ordinary admin write — unthrottled and free. What is
  scarce is a *token* for one, not the row.

The two coexist because they answer different questions, and the difference is
worth stating plainly since it looks like a contradiction: `seed.user()`
generates a unique username per call *by design* (enforced at runtime, pinned
by `seed-fixture.spec.ts`), while the principals are deliberately *fixed*. A
generated name is what stops four parallel workers colliding on rows they each
own; a fixed name is what lets four parallel workers share one token minted
before any of them started. **Default to `asPrincipal` when the test is about
authorization, and to `seed.user()` when the test is about a user.**

The principals are **shared and read-only**. Four workers hold the same two
identities simultaneously, so nothing may change a principal's `user_level`,
password, `channel_profiles` or existence — the damage would hit unrelated
tests mid-run and outlive it. A test that needs to *change* a user seeds one.
(`bootstrap` re-creates a deleted principal and corrects a drifted
`user_level` on the next run, but that repair costs a login and does not help
the run that broke it.)

### `asUser(username, password)` — the path that spends the budget

Still available, for the case no fixed principal can express: a user whose own
properties are the subject of the test, which therefore cannot be shared.
`seed.user()` generates a fresh username every call, so such a principal is a
guaranteed cache miss — one login, every run, per worker that drives it. Four
tests like that across four workers is four logins in a few seconds, and DRF
refuses the fourth in the window.

If you write one: budget it at **one per run**, say so in a comment at the call
site, and remember the cold path already spends the whole budget in bootstrap —
a run that is cold *and* calls `asUser` will 429, and a worker cannot wait out
a throttle window the way bootstrap can. `makeUserClient` logs a warning naming
the cost whenever it actually logs in, and its 429 error message says the
throttle is the harness budget rather than a product failure. The
worker-scoped counter behind that warning is exported as
`loginsSpentByThisWorker()`; `authorization.spec.ts` uses it to assert, as a
delta, that driving a fixed principal spends nothing.

Measuring it yourself: the container's nginx access log is the ground truth,
and it records 429s that never reach a test.

```bash
docker exec dispatcharr-e2e grep 'POST /api/accounts/token/ ' /var/log/nginx/access.log | tail
```

The trailing space matters — it excludes `token/refresh/`, which is free.

## The `IntervalSchedule` land mine — don't delete `e2e-harness-interval-prewarm-do-not-delete`

`bootstrap` creates one M3U account with that name and leaves it there
permanently. It is not test data and no test asserts on it. It exists to make
a product bug unreachable.

`core/scheduling.py` calls
`IntervalSchedule.objects.get_or_create(every=…, period=HOURS)` from an
`M3UAccount` `post_save` receiver, and `django_celery_beat.IntervalSchedule`
has no unique constraint on `(every, period)`. Two concurrent creates both
miss the SELECT and both INSERT; from then on every `get_or_create` for that
interval raises `MultipleObjectsReturned`, and **every M3U account and EPG
source creation on that container returns 500, permanently** — there is no UI
or API that can delete the duplicate row. Filed as
[D10Scot/Dispatcharr#7](https://github.com/D10Scot/Dispatcharr/issues/7); it
cost an agent an hour and four opaque test failures before it was understood.

`refresh_interval` defaults to `0`, which maps to `every=1, period=HOURS`, and
`EPGSource.refresh_interval` lands on the same row — so every default-shaped
create in the suite contends for one row. `bootstrap` runs serially, before
any parallel worker, so its create wins the race uncontended and every later
`get_or_create` is a plain SELECT hit.

Two things follow:

- **Deleting that account re-opens the window.** Deletion runs
  `_cleanup_orphaned_interval`, which removes the row again once nothing
  references it. Its `refresh_task` is what pins it.
- **A non-default `refresh_interval` needs the same care.** See the next
  section for the values this suite actually uses and the rule that keeps
  them from colliding.

`bootstrap` fails immediately, on **every** run, if the container is already
poisoned — saying so by name and giving `./scripts/e2e_up.sh --reset`. That
message is deliberate: the alternative is four unrelated tests failing later
with an opaque 500.

It has to check on every run rather than only the first, because a create that
500s still commits its `M3UAccount` row (the receiver raises *after* the
INSERT, and `ATOMIC_REQUESTS` is off), so the account exists with a null
`refresh_task` and its presence proves nothing. `bootstrap` therefore PATCHes
the account it finds — the same receiver runs on update — instead of returning
early on the name.

### Non-zero `refresh_interval` values, and what they cost

The set in use on this branch is **{0, 2, 3, 4, 8531, 8532}**, not just the
pre-warmed default: `e2e/tests/seeded/ws-fixture.spec.ts:50,51,109,121,122`
uses 2, 3 and 4, and `e2e/tests/seeded/async-wait.spec.ts:41,72` uses 8531 and
8532. The rule that keeps those from colliding with each other or with
`bootstrap`'s pre-warmed row is already stated in full at
`e2e/fixtures/types.ts:517-522` and at length in the header of
`ws-fixture.spec.ts:22-39`: `bootstrap` pre-warms the default (`0`, which maps
to `every=1`); any other value used from a parallel test must be **unique per
test** — not reused, and not pre-warmed from a worker, which is itself the
concurrent create that poisons the container (#7).

**If you add a test that uses a new non-zero value, add it to the set above.**
That list is an enumeration, so it is only as true as its last edit — and a
stale "here is the full set" is worse than no list at all, because the next
author picks a value they believe is unused. This section already had to be
rewritten once for exactly that reason.

That leaves one more thing to weigh before picking a non-zero value, not
covered by either of those two sources:

- **A non-zero interval also leaves an *enabled* beat task.**
  `create_or_update_periodic_task` (`core/scheduling.py`) computes
  `should_be_enabled = enabled and (use_cron or interval_hours > 0)`, so
  `refresh_interval: 0` yields a *disabled* `PeriodicTask` and anything else
  yields one that keeps re-refreshing that account for the life of the
  container — mutating rows under whatever test is running an hour later.

G3 also deliberately does **not** reproduce
[#7](https://github.com/D10Scot/Dispatcharr/issues/7): provoking it poisons the
shared container permanently for every remaining test in the run, and no
assertion is worth that. `COVERAGE.md` records that as a decision, not a gap.

## Writing a test

1. Read the root `CONTEXT.md`. Three different things are called "profile".
2. Import from `../../fixtures`, never `@playwright/test` directly — the
   fixtures module is what wires in `api`, `seed`, `asPrincipal` and the rest.
   `npm run typecheck` only catches a raw `@playwright/test` import when the
   spec destructures a custom fixture (the base `test`'s parameter type
   doesn't have it) — a spec that destructures only `page` typechecks clean
   and slips through (confirmed: `e2e/tests/seeded/authenticated-session.spec.ts`
   records the hole in a comment). Playwright itself still refuses such a
   spec at run time, once it does destructure a custom fixture, with "Test
   has unknown parameter" — but a `page`-only spec runs with no fixtures
   wired in and no error at all, silently bypassing the rule this item
   exists to enforce.
3. Seed what you need with `seed`; never assume the instance is empty. It
   never is — every project shares one container across the whole suite.
4. The fixture signatures are typed, and `npm run typecheck` is the gate. Pass
   the response type where one is asked for (`waitFor.resource<Channel>(…)`,
   `api.json<Channel>(res, …)`) — the entity types are exported from
   `../../fixtures`, and neither of those two has an `any` default, so
   omitting the argument leaves you with `unknown` rather than a free pass. If a field you need is missing from one, **add it to
   `e2e/fixtures/types.ts` with evidence** (the serializer, the model's
   nullability, a live response); do not cast. A cast makes the same claim
   without the check, one call site at a time. See "Types" below.
5. Never assert a global count or an unfiltered list — another test's data,
   or another worker running concurrently, will make those flake or lie.
   Filter on the name your `seed` call generated.
6. Never assert on a notification toast. That doesn't flake so much as it
   turns what should be a backend/API-level assertion into a frontend one —
   assert the underlying state through `api`/`waitFor` instead, and leave
   toast rendering to a frontend-focused test.
7. Acting as a non-admin? Use `asPrincipal('streamer' | 'standard')` — it is
   free at any worker count. `asUser` costs one login out of three a minute;
   read the login throttle section above before you reach for it.
8. New to the harness? `authenticated-session.spec.ts`, `authorization.spec.ts`,
   `async-wait.spec.ts` (two exemplars in one file) and `stream-client.spec.ts`
   (under `tests/seeded` and `tests/streaming`) each carry an "Exemplar:"
   comment for exactly this — read the one closest to what you're writing.
9. Update `COVERAGE.md` in the same PR as the test.
10. Found a product bug? Don't patch the product from this harness. Assert
   the *correct* behaviour, mark the test `test.fail()`, and file it:
   `gh issue create --repo D10Scot/Dispatcharr`. The `--repo` flag is
   mandatory here — this checkout is a fork, and `gh` without it resolves to
   upstream's public tracker, not this fork's.

## CI

`.github/workflows/e2e-tests.yml` builds the AIO image once, then runs
`pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`
and `lifecycle` as a hardcoded six-job matrix (the `test` job's
`matrix.project` list in `e2e-tests.yml`), each
against its own fresh container, each gated on `npm run typecheck` before
tests run. **If you add another project to `playwright.config.ts`, add it to
that matrix too** — nothing wires new projects in automatically, and a project
missing from the matrix gets no CI coverage and no failure signal.

A red E2E run **does** block a merge: the `Main` ruleset is active and
requires one check, **`E2E result`**. That is the aggregate job at the bottom
of `e2e-tests.yml`, not the matrix jobs themselves — and the distinction is
load-bearing. A matrix job cannot be a required check here, because when the
`changes` job decides the suite is unnecessary the matrix is skipped *before
expansion*, so no check by that name ever reports, and a required check that
never reports blocks the merge forever. `E2E result` runs with `if: always()`
so it always reports, and passes only when everything it depends on either
succeeded or was deliberately skipped. That is also why `e2e-tests.yml`'s
`pull_request` trigger deliberately carries no `paths:` filter.

`lifecycle-upgrade` is the one project **deliberately not** in that matrix.
It runs instead in `.github/workflows/lifecycle-tests.yml`, because it pulls
a ~3.6 GB baseline image and takes roughly 9 minutes — adding that to every
PR would roughly double E2E latency, where the longest existing job in
`e2e-tests.yml` is 284s. That workflow also runs the two bash suites,
`docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh`, which had no
workflow at all before it. **`lifecycle-tests.yml` is path-filtered and must
not be made a required check** — a required check on a workflow that never
triggers for an unrelated PR blocks the merge forever, which is exactly why
`e2e-tests.yml`'s own `pull_request` trigger carries no paths filter.

Both bash suites need **bash 4.4+** to run. Stock macOS `/bin/bash` is
3.2.57, where expanding an empty array under `set -u` is an unbound-variable
error, so the suite dies on `CLEANUP_ITEMS[@]` before running a single
scenario — CI runners ship bash 5.x, so this only bites locally, on the
platform this repo is maintained from. Homebrew's `bash`, or a `docker:27-cli`
container with bash installed, both work.

## Architecture note

Local builds are native-architecture; CI is amd64. If you need parity,
`--platform linux/amd64` works but QEMU makes the streaming suite unusable.

## Fixtures

| Fixture | Provides |
|---|---|
| `api` | Authenticated HTTP; retries once through a token refresh on 401. `upload()` is the one multipart path |
| `seed` | `channel`, `user`, `channelProfile`, `streamProfile`, `m3uAccount`, `epgSource`, `stream`, `upstreamChannel`, `upstreamM3UAccount`, `upstreamEpgSource`, `logo` |
| `adminPage` | A `Page` authenticated as the bootstrap admin |
| `asPrincipal` | An `ApiClient` for a fixed principal, `'streamer'` (level 0) or `'standard'` (level 1). Free |
| `asUser` | An `ApiClient` for an arbitrary principal. Costs a login — see the throttle section |
| `waitFor` | `condition`, `resource`, `m3uRefreshComplete`, `epgRefreshComplete` |
| `ws` | `/ws/` subscription; `waitForMessage(type, { where, timeoutMs })` |
| `streamClient` | `open`, `readPackets`, `collectFor`, `close` |
| `upstream` | The fake upstream provider: `scenario`, `fault`, `rate`, `clearFault`, `log`, `toControl`. Test-scoped, not worker-scoped — `attachLogs` needs `testInfo` to attach a failing scenario's log to the Playwright report, which a worker fixture cannot obtain. See `e2e-upstream/README.md` and the section above on the two-container topology |

Plus three exports that are not fixtures, from the same `../../fixtures` module:

| Export | Provides |
|---|---|
| `expectTsAligned(buffer)` | Asserts a buffer is 188-byte-aligned MPEG-TS — whole packets, `0x47` on every boundary. The assertion byte-level streaming tests are built on; reach for it before hand-rolling one |
| `TS_PACKET_SIZE` / `TS_SYNC_BYTE` | `188` and `0x47`, for tests doing their own arithmetic |
| `SEEDED_USER_PASSWORD` | The password `seed.user()` assigns — import it rather than repeating the literal |

### Types — the contract is enforced, not just described

Every `seed` factory takes an `overrides` object typed to that endpoint's
*writable* fields and returns that entity's response type, both defined in
`e2e/fixtures/types.ts` and re-exported from `../../fixtures`. So
`seed.channel({ nmae: 'x' })` fails `npm run typecheck` rather than being
silently dropped by DRF, which ignores unknown keys on write.

Three things about them are worth knowing before you use them:

- **They are not the serializers.** They are the subset this harness has
  verified against the live API and the model definitions. Missing a field?
  Add it there, having checked it, rather than casting at the call site.
- **The identity field is absent on purpose.** `name` is not in
  `ChannelOverrides` and `username` is not in `UserOverrides`, because the
  factory generates them and spreads them *after* your overrides — passing one
  does nothing. `ChannelProfileOverrides` is empty for the same reason: `name`
  is the only writable field that endpoint has.
- **The compile-time check is not the enforcement.** TypeScript only
  excess-property-checks a fresh object literal, and nothing type-checks a body
  that arrived from `JSON.parse` or through an `as`. The runtime spread order
  in `seed.ts` is what actually holds; `seed-fixture.spec.ts` pins both halves.

`waitFor.resource<T>` has no default for `T`, and `ws.waitForMessage` returns a
`WsMessage` whose `type` and `data` are **both optional** — the product really
does send messages missing either — so read a payload as `message.data?.x`.

### `ws` is a shared broadcast — read this before waiting on a type

`/ws/` puts every socket in one group, `updates` (`dispatcharr/consumers.py`),
and `seeded` runs **4 workers against one container**, so your socket receives
the other three workers' events interleaved with your own. A bare
`waitForMessage('playlist_created')` resolves on *whoever's* playlist was
created — your own work may not have happened yet, and the assertion after it
either flakes or passes on another test's data.

Correlate with a predicate whenever the type is not exclusively yours:

```ts
const account = await seed.m3uAccount();
const message = await ws.waitForMessage('playlist_created', {
  where: (data) => data.playlist_id === account.id,
});
```

`where` receives `message.data`, which is where product events carry their
entity ids, and is evaluated as each message arrives — so obtain the id
*before* you start waiting. A bare type match is safe only for something
nothing else can produce; `connection_established`, which is per socket, is
the honest example.

Messages are consumed, not replayed: two sequential waits for one type return
two *different* messages, and a wait that times out is deregistered, so it
cannot swallow the event a later wait is waiting for.
`e2e/tests/seeded/ws-fixture.spec.ts` pins all three.

`e2e/fixtures/index.ts` opens with the full method inventory for all seven
fixtures. That header, this file, the root `CONTEXT.md` and `COVERAGE.md` are
meant to be enough to write a test without opening a fixture; if you had to,
say so in the PR — that is a documentation bug.
