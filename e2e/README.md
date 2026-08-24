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
| `./scripts/e2e_up.sh --down` | Destroy container + volume, start nothing |

`DISPATCHARR_E2E_PORT`, `_CONTAINER`, `_VOLUME` and `_IMAGE` override the
defaults, and every command above respects them.

**The container is published on `127.0.0.1` only.** Once bootstrap has run it
holds a superuser whose password is committed to this repository in plain
text, so it must not be reachable from the LAN — a peer on your network would
otherwise have an admin account on it. A container created *before* this was
the case keeps its old binding: `--down`, then start again, to pick the new
one up. CI binds the same way.

## Projects

| Project | What it is for |
|---|---|
| `bootstrap` | Creates the superuser, pre-warms the `IntervalSchedule` row (see below) and writes auth state. Runs automatically as a dependency of `seeded` and `streaming` |
| `pristine` | Needs an instance with no superuser: first-run, migrations, PUID/PGID |
| `seeded` | The default. Shared instance, parallel workers, API-seeded data |
| `streaming` | Byte-level tests. Long timeouts, fewer workers |

`pristine` deliberately has no `bootstrap` dependency — it needs the
superuser *not* to exist yet, which is the entire point of that project, and
is why `pristine` and `seeded` cannot share a container. `bootstrap` consumes
the first-run state, so run them separately, resetting between:

```bash
./scripts/e2e_up.sh --reset && npm run test:pristine
./scripts/e2e_up.sh --reset && npm run test:seeded
```

`npm test` (no suffix) deliberately fails with a message telling you to pick
one of the three — there is no single invocation that is correct for all of
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

## The login throttle — read this before writing a multi-user test

`POST /api/accounts/token/` is rate-limited to **3 requests per minute per
client IP** (`dispatcharr/settings.py:309-310` sets `"login": "3/minute"`;
enforced by `LoginRateThrottle` at `apps/accounts/throttling.py:20`, applied
to the view at `apps/accounts/api_views.py:57`). The budget is shared with
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

| Path | Logins |
|---|---|
| Full run, warm (`principals.json` + `tokens.json` present) | **0** |
| More than 30 min since the last run (access tokens expired) | **0** — renewed through the *unthrottled* refresh endpoint |
| Cold: first run after `--reset`, deleted auth files, or >1 day (`SIMPLE_JWT.REFRESH_TOKEN_LIFETIME`) | **3** = 1 admin + 1 per principal, exactly the per-minute cap |
| Each `asUser()` call for a principal not in the roster | **+1**, per distinct `username:password`, *per worker* |

`TokenRefreshView` is **not** throttled (`apps/accounts/api_views.py:133`
carries no `throttle_classes`, and `DEFAULT_THROTTLE_CLASSES` is `[]`), which
is what makes the middle row free: an access token lives 30 minutes, a refresh
token a day, so bootstrap and `ApiClient` both renew rather than re-login.

The cold path sits exactly on the cap, so **adding a principal pushes it over**
and makes the first run after a reset wait out a throttle window.
`provisionPrincipals` handles that rather than failing — it honours
`Retry-After` and retries, which is why the `bootstrap` project has a
180-second timeout — but it is a real cost, so add a principal only when no
existing one can express the case.

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

`core/scheduling.py:121` calls
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
- **A non-default `refresh_interval` is not covered.** If you write a test
  that creates accounts with, say, `refresh_interval: 6` from parallel
  workers, they race for the `(6, HOURS)` row. Pre-warm it the same way.

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
4. Never assert a global count or an unfiltered list — another test's data,
   or another worker running concurrently, will make those flake or lie.
   Filter on the name your `seed` call generated.
5. Never assert on a notification toast. That doesn't flake so much as it
   turns what should be a backend/API-level assertion into a frontend one —
   assert the underlying state through `api`/`waitFor` instead, and leave
   toast rendering to a frontend-focused test.
6. Acting as a non-admin? Use `asPrincipal('streamer' | 'standard')` — it is
   free at any worker count. `asUser` costs one login out of three a minute;
   read the login throttle section above before you reach for it.
7. New to the harness? `authenticated-session.spec.ts`, `authorization.spec.ts`,
   `async-wait.spec.ts` (two exemplars in one file) and `stream-client.spec.ts`
   (under `tests/seeded` and `tests/streaming`) each carry an "Exemplar:"
   comment for exactly this — read the one closest to what you're writing.
8. Update `COVERAGE.md` in the same PR as the test.
9. Found a product bug? Don't patch the product from this harness. Assert
   the *correct* behaviour, mark the test `test.fail()`, and file it:
   `gh issue create --repo D10Scot/Dispatcharr`. The `--repo` flag is
   mandatory here — this checkout is a fork, and `gh` without it resolves to
   upstream's public tracker, not this fork's.

## CI

`.github/workflows/e2e-tests.yml` builds the AIO image once, then runs
`pristine`, `seeded` and `streaming` as a hardcoded three-job matrix
(`e2e-tests.yml:49-50`), each against its own fresh container, each gated on
`npm run typecheck` before tests run. **If you add a fourth project to
`playwright.config.ts`, add it to that matrix too** — nothing wires new
projects in automatically, and a project missing from the matrix gets no CI
coverage and no failure signal.

These three jobs are **not** required checks on `main` — nobody has configured
branch protection on this fork, so a red E2E run does not block a merge today.
Making them required is a one-time step in the repository settings, not
something this workflow can do for itself.

## Architecture note

Local builds are native-architecture; CI is amd64. If you need parity,
`--platform linux/amd64` works but QEMU makes the streaming suite unusable.

## Fixtures

| Fixture | Provides |
|---|---|
| `api` | Authed HTTP; retries once through a token refresh on 401 |
| `seed` | `channel`, `user`, `channelProfile`, `streamProfile`, `m3uAccount`, `epgSource` |
| `adminPage` | A `Page` authenticated as the bootstrap admin |
| `asPrincipal` | An `ApiClient` for a fixed principal, `'streamer'` (level 0) or `'standard'` (level 1). Free |
| `asUser` | An `ApiClient` for an arbitrary principal. Costs a login — see the throttle section |
| `waitFor` | `condition`, `resource`, `m3uRefreshComplete` |
| `ws` | `/ws/` subscription; `waitForMessage(type, { where, timeoutMs })` |
| `streamClient` | `open`, `readPackets`, `collectFor`, `close` |

Plus three exports that are not fixtures, from the same `../../fixtures` module:

| Export | Provides |
|---|---|
| `expectTsAligned(buffer)` | Asserts a buffer is 188-byte-aligned MPEG-TS — whole packets, `0x47` on every boundary. The assertion byte-level streaming tests are built on; reach for it before hand-rolling one |
| `TS_PACKET_SIZE` / `TS_SYNC_BYTE` | `188` and `0x47`, for tests doing their own arithmetic |
| `SEEDED_USER_PASSWORD` | The password `seed.user()` assigns — import it rather than repeating the literal |

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
