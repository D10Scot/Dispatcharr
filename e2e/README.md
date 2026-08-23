# E2E Tests

Playwright against a real Dispatcharr AIO container.

## Quick start

```bash
./scripts/e2e_up.sh --reset     # build + run a fresh container
cd e2e
npm ci
npx playwright install --with-deps chromium
npm run test:seeded
```

## Projects

| Project | What it is for |
|---|---|
| `bootstrap` | Creates the superuser and writes auth state. Runs automatically as a dependency |
| `pristine` | Needs an instance with no superuser: first-run, migrations, PUID/PGID |
| `seeded` | The default. Shared instance, parallel workers, API-seeded data |
| `streaming` | Byte-level tests. Long timeouts, fewer workers |

`pristine` and `seeded` cannot share a container — `bootstrap` consumes the
first-run state. Run them separately, resetting between:

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
to private/loopback addresses (`dispatcharr/utils.py:142`). Against a public
instance, set `DISPATCHARR_SETUP_ALLOWED_IP` on that instance first.

## The login throttle — read this before writing a multi-user test

`POST /api/accounts/token/` is rate-limited to **3 requests per minute per
client IP** (`dispatcharr/settings.py:309-310` sets `"login": "3/minute"`;
enforced by `LoginRateThrottle` at `apps/accounts/throttling.py:20`, applied
to the view at `apps/accounts/api_views.py:57`). The budget is shared with
Django admin login — both go through the same throttle scope.

Every run from one host is one client IP, so **the entire suite, across all
workers, shares three logins per minute.** This is invisible until it bites,
and when it does it looks like a flaky product bug (a 429 with no obvious
cause), not a harness limit — read this section before you go looking for
one.

Current spend, in this harness:

- `bootstrap` costs **0** logins in steady state: it reuses a still-valid
  token from `playwright/.auth/tokens.json` (`e2e/setup/bootstrap.setup.ts`).
  It costs **1** on a cold path — first run after a container reset, missing
  auth files, or a token older than the 30-minute access lifetime
  (`SIMPLE_JWT.ACCESS_TOKEN_LIFETIME`, `dispatcharr/settings.py:452`).
- Each **distinct** `asUser` principal costs 1 login
  (`e2e/fixtures/auth.ts`).
- `makeUserClient` caches token pairs keyed on `username:password`, so
  repeated `asUser` calls for the *same* principal are free after the first.
- `TokenRefreshView` is **not** throttled (`apps/accounts/api_views.py:133`
  carries no `throttle_classes`) — refreshing an expiring access token costs
  nothing from the login budget. `ApiClient` already does this automatically
  on a 401.

**The trap:** `seed.user()` generates a unique username on every call
(`e2e/fixtures/seed.ts`), so a test that seeds a fresh principal per test
gets **no cache benefit at all** — every `asUser` call for it is a guaranteed
miss. An authorization matrix seeding a new user per test, spread across
parallel workers, will 429 on its third distinct principal within any
60-second window. `makeUserClient` throws on a non-OK login response, so this
surfaces as a hard test failure, not a retry.

**The remedy, for whichever goal needs a real matrix:** seed a small, fixed
set of principals **once per worker** (a `worker`-scoped Playwright fixture)
and have every test in that worker reuse them. That's what makes the
username-keyed cache in `makeUserClient` start hitting. This harness does not
implement that fixture — G1 has no test that needs it, and building it
speculatively would be guessing at a shape the consuming goal hasn't asked
for yet. If you're the goal that needs it, build it then; this paragraph is
so you inherit the analysis instead of rediscovering it through a mystery
429.

## Writing a test

1. Read the root `CONTEXT.md`. Three different things are called "profile".
2. Import from `../../fixtures`, never `@playwright/test` directly — the
   fixtures module is what wires in `api`, `seed`, `asUser` and the rest, and
   importing the raw package silently drops all of them.
3. Seed what you need with `seed`; never assume the instance is empty. It
   never is — every project shares one container across the whole suite.
4. Never assert a global count, an unfiltered list, or a notification toast.
   Another test's data, or another worker running concurrently, will make
   those flake or lie. Filter on the name your `seed` call generated.
5. Update `COVERAGE.md` in the same PR as the test.
6. Found a product bug? Don't patch the product from this harness. Assert
   the *correct* behaviour, mark the test `test.fail()`, and file it:
   `gh issue create --repo D10Scot/Dispatcharr`. The `--repo` flag is
   mandatory here — this checkout is a fork, and `gh` without it resolves to
   upstream's public tracker, not this fork's.

## Architecture note

Local builds are native-architecture; CI is amd64. If you need parity,
`--platform linux/amd64` works but QEMU makes the streaming suite unusable.

## Fixtures

| Fixture | Provides |
|---|---|
| `api` | Authed HTTP; retries once through a token refresh on 401 |
| `seed` | `channel`, `user`, `channelProfile`, `streamProfile`, `m3uAccount`, `epgSource` |
| `adminPage` | A `Page` authenticated as the bootstrap admin |
| `asUser` | An `ApiClient` for a non-admin principal |
| `waitFor` | `condition`, `resource`, `m3uRefreshComplete` |
| `ws` | `/ws/` subscription; `waitForMessage(type)` |
| `streamClient` | `open`, `readPackets`, `collectFor`, `close` |
