# E2E Harness Foundation (G1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Playwright fixture layer, project topology and CI wiring that five wave-2 E2E goals will code against.

**Architecture:** One AIO container per CI job, seeded through the DRF API rather than the UI. A `bootstrap` setup project mints a superuser and persists auth state; three test projects (`pristine`, `seeded`, `streaming`) consume it. Every seeded entity carries a per-worker name prefix so parallel workers cannot collide. Byte-level streaming uses Node `fetch`, not Playwright's `request`, because `APIResponse.body()` buffers the whole response and the stream endpoint never ends.

**Tech Stack:** Playwright 1.62.1 (pinned via `e2e/package-lock.json`), TypeScript, Node 24, Docker.

**Spec:** `docs/superpowers/specs/2026-08-23-e2e-harness-foundation-design.md`

## Global Constraints

- **Playwright is pinned at `1.62.1`.** Install with `npm ci`, never `npm install`. Do not bump it in this plan.
- **All new code is TypeScript** under `e2e/`. The rest of the repo stays as it is; do not convert `frontend/`.
- **localStorage auth keys are exactly `accessToken`, `refreshToken`, `tokenExpiration`.** There is no `token` key — `frontend/src/api.js:192` clears one, but nothing writes it. Using `token` authenticates nobody and dumps the test on `/login` with no error.
- **`tokenExpiration` is the access token's `exp` claim in unix seconds, stored as a string.** `frontend/src/store/auth.jsx:168–173` refreshes whenever it is missing or past.
- **Generated names must match `^[A-Za-z0-9._@-]+$`** (`apps/accounts/serializers.py:16`). Hyphens, dots, underscores and `@` only.
- **Never assert on a global count or an unfiltered list.** The instance is shared and is never empty.
- **Never assert on notification toasts.**
- **API base paths:** `/api/accounts/`, `/api/channels/`, `/api/core/`, `/api/m3u/`, `/api/epg/`.
- **Do not fix product bugs found while building this.** File them: `gh issue create --repo D10Scot/Dispatcharr`. The explicit `--repo` flag is mandatory (`docs/agents/issue-tracker.md`).

---

## File Structure

| File | Responsibility |
|---|---|
| `e2e/tsconfig.json` | TypeScript config; no emit, Playwright transpiles |
| `e2e/playwright.config.ts` | Four projects, shared `use`, per-project timeouts |
| `e2e/setup/bootstrap.setup.ts` | Create superuser, mint JWT, write auth state + tokens |
| `e2e/fixtures/api.ts` | `ApiClient` — authed HTTP with transparent 401→refresh |
| `e2e/fixtures/seed.ts` | `Seeder` — namespaced entity factories |
| `e2e/fixtures/auth.ts` | `asUser()` — non-admin contexts |
| `e2e/fixtures/wait.ts` | `waitFor` — REST polling helpers |
| `e2e/fixtures/ws.ts` | `WsListener` — `/ws/` subscription |
| `e2e/fixtures/stream-client.ts` | `StreamClient` — Node fetch, TS-packet aware |
| `e2e/fixtures/index.ts` | The single import surface for wave 2 |
| `e2e/tests/pristine/` | Fresh-instance-only specs |
| `e2e/tests/seeded/` | The default population |
| `e2e/tests/streaming/` | Byte-level, long timeouts |
| `scripts/e2e_up.sh` | Build + run a local container; `--reset` wipes it |
| `CONTEXT.md` | Product glossary (repo root) |
| `e2e/COVERAGE.md` | Inventory across all seven goals |
| `docs/adr/0001-e2e-shared-api-seeded-container.md` | The isolation decision |
| `.github/workflows/e2e-tests.yml` | build → artifact → three consumers |

---

### Task 1: TypeScript migration, project topology, local runner

Converts `e2e/` to TypeScript and stands up the four-project config with the existing test moved into `pristine`. Ships `scripts/e2e_up.sh` because every later task needs a running container to test against.

**Files:**
- Create: `e2e/tsconfig.json`, `e2e/playwright.config.ts`, `scripts/e2e_up.sh`
- Create: `e2e/tests/pristine/first-run-setup-and-login.spec.ts`
- Delete: `e2e/playwright.config.js`, `e2e/tests/first-run-setup-and-login.spec.js`
- Modify: `e2e/package.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/e2e_up.sh` (`--reset` flag); npm scripts `test:pristine`, `test:seeded`, `test:streaming`; the four project names `bootstrap`, `pristine`, `seeded`, `streaming`.

- [ ] **Step 1: Add TypeScript dependencies**

```bash
cd e2e && npm install --save-dev typescript@5.7.2 @types/node@24.0.0
```

- [ ] **Step 2: Write `e2e/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022", "DOM"],
    "types": ["node"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Write `e2e/playwright.config.ts`**

`pristine` deliberately has no `dependencies` — it runs on a container with no superuser, which `bootstrap` would consume. CI selects one project per job with `--project`.

```ts
import { defineConfig } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:9191';

export default defineConfig({
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'bootstrap',
      testDir: './setup',
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: 'pristine',
      testDir: './tests/pristine',
      workers: 1,
      fullyParallel: false,
    },
    {
      name: 'seeded',
      testDir: './tests/seeded',
      dependencies: ['bootstrap'],
      fullyParallel: true,
      workers: 4,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      name: 'streaming',
      testDir: './tests/streaming',
      dependencies: ['bootstrap'],
      timeout: 300_000,
      workers: 2,
    },
  ],
});
```

- [ ] **Step 4: Replace `e2e/package.json` scripts**

```json
{
  "name": "dispatcharr-e2e",
  "private": true,
  "version": "1.0.0",
  "scripts": {
    "test": "playwright test",
    "test:pristine": "playwright test --project=pristine",
    "test:seeded": "playwright test --project=seeded",
    "test:streaming": "playwright test --project=streaming",
    "typecheck": "tsc --noEmit"
  }
}
```

Keep the existing `devDependencies` block and add the two from Step 1.

- [ ] **Step 5: Move the existing spec to `e2e/tests/pristine/first-run-setup-and-login.spec.ts`**

Content is unchanged from `e2e/tests/first-run-setup-and-login.spec.js` — it is already valid TypeScript. Copy it verbatim, then `git rm` the `.js` original and `e2e/playwright.config.js`.

- [ ] **Step 6: Write `scripts/e2e_up.sh`**

```bash
#!/usr/bin/env bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh          start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset  destroy container + volume first
set -euo pipefail

NAME="${DISPATCHARR_E2E_CONTAINER:-dispatcharr-e2e}"
VOLUME="${DISPATCHARR_E2E_VOLUME:-dispatcharr-e2e-data}"
IMAGE="${DISPATCHARR_E2E_IMAGE:-dispatcharr-e2e:local}"
PORT="${DISPATCHARR_E2E_PORT:-9191}"

if [[ "${1:-}" == "--reset" ]]; then
  echo "Removing container and volume..."
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE for the native architecture..."
  docker build -f docker/Dockerfile -t "$IMAGE" .
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  # /data must be a mounted volume: the entrypoint has no fallback and
  # crashes on mktemp against a nonexistent directory.
  docker run -d --name "$NAME" \
    -p "${PORT}:9191" \
    -v "${VOLUME}:/data" \
    -e DISPATCHARR_ENV=aio \
    -e DISPATCHARR_LOG_LEVEL=info \
    "$IMAGE" >/dev/null
fi

echo -n "Waiting for the app"
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "http://localhost:${PORT}/api/accounts/initialize-superuser/"; then
    echo " — ready at http://localhost:${PORT}"
    exit 0
  fi
  echo -n "."
  sleep 5
done

echo " — never became ready. Container logs:"
docker logs "$NAME" || true
exit 1
```

Then: `chmod +x scripts/e2e_up.sh`

- [ ] **Step 7: Start a fresh container and run the pristine suite**

```bash
./scripts/e2e_up.sh --reset
cd e2e && npm ci && npx playwright install --with-deps chromium && npm run test:pristine
```

Expected: 1 passed. This is the pre-existing test, so a failure here means the migration broke something, not the product.

- [ ] **Step 8: Verify types compile**

Run: `cd e2e && npm run typecheck`
Expected: no output, exit 0.

- [ ] **Step 9: Commit**

```bash
git add e2e scripts/e2e_up.sh
git commit -m "test(e2e): migrate harness to TypeScript, add four-project topology

Splits the suite into bootstrap/pristine/seeded/streaming projects and moves
the existing first-run test into pristine, which is the only population that
can run against an instance with no superuser.

Adds scripts/e2e_up.sh so the container can be built and reset locally
without memorising the docker run invocation (/data must be a volume; the
entrypoint crashes without it)."
```

---

### Task 2: Bootstrap project — superuser and persisted auth state

**Files:**
- Create: `e2e/setup/bootstrap.setup.ts`
- Create: `e2e/tests/seeded/authenticated-session.spec.ts`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: project names from Task 1.
- Produces: `ADMIN` (`{ username, password, email }`), `playwright/.auth/admin.json` (Playwright storageState), `playwright/.auth/tokens.json` (`{ access, refresh, username, password, email }`).

- [ ] **Step 1: Write the failing test — `e2e/tests/seeded/authenticated-session.spec.ts`**

```ts
import { test, expect } from '@playwright/test';

// Exemplar: the seeded project's storageState authenticates without ever
// touching the login form. If this fails, bootstrap wrote the wrong keys.
test('seeded project lands authenticated on /channels', async ({ page }) => {
  await page.goto('/channels');

  await expect(page).toHaveURL(/\/channels/);
  await expect(page.getByText('Please log in to continue.')).toHaveCount(0);
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd e2e && npm run test:seeded`
Expected: FAIL — `bootstrap` has no matching tests, so `playwright/.auth/admin.json` does not exist and the project errors on the missing storageState file.

- [ ] **Step 3: Write `e2e/setup/bootstrap.setup.ts`**

```ts
import { test as setup, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

export const ADMIN = {
  username: 'e2e-admin',
  password: 'Correct-Horse-Battery-Staple-42!',
  email: 'e2e-admin@example.com',
};

const AUTH_DIR = 'playwright/.auth';
const STATE_FILE = path.join(AUTH_DIR, 'admin.json');
const TOKENS_FILE = path.join(AUTH_DIR, 'tokens.json');

/** The access token's `exp` claim, in unix seconds. */
function jwtExp(accessToken: string): number {
  const payload = accessToken.split('.')[1];
  return JSON.parse(Buffer.from(payload, 'base64').toString('utf8')).exp;
}

setup('create the superuser and persist admin auth state', async ({
  request,
  baseURL,
}) => {
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(status.ok()).toBeTruthy();

  if (!(await status.json()).superuser_exists) {
    // POST is IP-gated to private/loopback (dispatcharr/utils.py:142). Fine
    // from CI and from localhost; a public E2E_BASE_URL needs
    // DISPATCHARR_SETUP_ALLOWED_IP set on the instance.
    const created = await request.post('/api/accounts/initialize-superuser/', {
      data: ADMIN,
    });
    expect(
      created.ok(),
      `superuser creation failed: ${created.status()} ${await created.text()}`
    ).toBeTruthy();
  }

  const tokenRes = await request.post('/api/accounts/token/', {
    data: { username: ADMIN.username, password: ADMIN.password },
  });
  expect(
    tokenRes.ok(),
    `login failed: ${tokenRes.status()} ${await tokenRes.text()}`
  ).toBeTruthy();
  const { access, refresh } = await tokenRes.json();

  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.writeFileSync(
    TOKENS_FILE,
    JSON.stringify({ access, refresh, ...ADMIN }, null, 2)
  );

  // Three keys, exactly these names. frontend/src/store/auth.jsx:186-190 is
  // the only writer; api.js:192 clears a `token` key nothing ever sets.
  fs.writeFileSync(
    STATE_FILE,
    JSON.stringify(
      {
        cookies: [],
        origins: [
          {
            origin: new URL(baseURL!).origin,
            localStorage: [
              { name: 'accessToken', value: access },
              { name: 'refreshToken', value: refresh },
              { name: 'tokenExpiration', value: String(jwtExp(access)) },
            ],
          },
        ],
      },
      null,
      2
    )
  );
});
```

- [ ] **Step 4: Ignore the auth artifacts**

Append to `.gitignore`:

```
# E2E auth state — contains live JWTs
e2e/playwright/.auth/
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
./scripts/e2e_up.sh --reset
cd e2e && npm run test:seeded
```

Expected: `bootstrap` runs first, then 1 passed.

- [ ] **Step 6: Commit**

```bash
git add e2e .gitignore
git commit -m "test(e2e): add bootstrap project minting admin auth state

Creates the superuser via the REST API and writes both a Playwright
storageState and the raw token pair. The storageState carries three
localStorage keys — accessToken, refreshToken, tokenExpiration — matching
store/auth.jsx exactly. api.js clears a 'token' key on its 401 path but
nothing writes it; using that name authenticates nobody and silently
redirects to /login."
```

---

### Task 3: `api` fixture with transparent token refresh

Access tokens live 30 minutes (`dispatcharr/settings.py:452`). A suite that runs longer starts 401-ing intermittently.

**Files:**
- Create: `e2e/fixtures/api.ts`, `e2e/fixtures/index.ts`
- Create: `e2e/tests/seeded/api-fixture.spec.ts`

**Interfaces:**
- Consumes: `playwright/.auth/tokens.json` from Task 2.
- Produces: `class ApiClient` with `get(url)`, `post(url, data)`, `patch(url, data)`, `delete(url)` → `Promise<APIResponse>`, and `expireAccessTokenForTest()`. Exported fixture `api: ApiClient`.

- [ ] **Step 1: Write the failing test — `e2e/tests/seeded/api-fixture.spec.ts`**

```ts
import { test, expect } from '../../fixtures';

test('api fixture authenticates against a protected endpoint', async ({ api }) => {
  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);
});

test('api fixture recovers from an expired access token', async ({ api }) => {
  // Simulate the 30-minute expiry without waiting for it.
  api.expireAccessTokenForTest();

  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd e2e && npm run test:seeded -- api-fixture`
Expected: FAIL — `Cannot find module '../../fixtures'`.

- [ ] **Step 3: Write `e2e/fixtures/api.ts`**

```ts
import type { APIRequestContext, APIResponse } from '@playwright/test';
import fs from 'node:fs';

const TOKENS_FILE = 'playwright/.auth/tokens.json';

type Tokens = {
  access: string;
  refresh: string;
  username: string;
  password: string;
  email: string;
};

/**
 * Authenticated HTTP client. Retries once through a token refresh on 401,
 * because SIMPLE_JWT.ACCESS_TOKEN_LIFETIME is 30 minutes and suites outlive it.
 */
export class ApiClient {
  private tokens: Tokens;

  constructor(private ctx: APIRequestContext) {
    this.tokens = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
  }

  /** Test hook: corrupt the access token so the next call takes the 401 path. */
  expireAccessTokenForTest(): void {
    this.tokens.access = 'expired.invalid.token';
  }

  private async refresh(): Promise<void> {
    const res = await this.ctx.post('/api/accounts/token/refresh/', {
      data: { refresh: this.tokens.refresh },
    });
    if (!res.ok()) {
      throw new Error(
        `token refresh failed: ${res.status()} ${await res.text()}`
      );
    }
    this.tokens.access = (await res.json()).access;
  }

  private async send(
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
    url: string,
    data?: unknown
  ): Promise<APIResponse> {
    const options = () => ({
      method,
      headers: { Authorization: `Bearer ${this.tokens.access}` },
      ...(data === undefined ? {} : { data }),
    });

    let res = await this.ctx.fetch(url, options());
    if (res.status() === 401) {
      await this.refresh();
      res = await this.ctx.fetch(url, options());
    }
    return res;
  }

  get(url: string) {
    return this.send('GET', url);
  }
  post(url: string, data: unknown) {
    return this.send('POST', url, data);
  }
  patch(url: string, data: unknown) {
    return this.send('PATCH', url, data);
  }
  delete(url: string) {
    return this.send('DELETE', url);
  }

  /** JSON body of a call asserted to have succeeded. */
  async json<T = any>(res: APIResponse, context: string): Promise<T> {
    if (!res.ok()) {
      throw new Error(`${context}: ${res.status()} ${await res.text()}`);
    }
    return res.json();
  }
}
```

- [ ] **Step 4: Write `e2e/fixtures/index.ts`**

```ts
import { test as base } from '@playwright/test';
import { ApiClient } from './api';

export type Fixtures = {
  api: ApiClient;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
});

export { expect } from '@playwright/test';
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e && npm run test:seeded -- api-fixture`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add e2e/fixtures e2e/tests/seeded/api-fixture.spec.ts
git commit -m "test(e2e): add api fixture with transparent token refresh

SIMPLE_JWT.ACCESS_TOKEN_LIFETIME is 30 minutes, so a token minted in
bootstrap goes stale part-way through a growing suite. Browser tests
self-heal via store/auth.jsx; raw API helpers would 401 intermittently as a
function of suite duration. The client retries once through
/api/accounts/token/refresh/."
```

---

### Task 4: `seed` fixture — namespaced entity factories

**Files:**
- Create: `e2e/fixtures/seed.ts`
- Modify: `e2e/fixtures/index.ts`
- Create: `e2e/tests/seeded/seed-fixture.spec.ts`

**Interfaces:**
- Consumes: `ApiClient` from Task 3.
- Produces: `class Seeder` with `channel(overrides?)`, `user(overrides?)`, `channelProfile(overrides?)`, `streamProfile(overrides?)`, `m3uAccount(overrides?)`, `epgSource(overrides?)`, each returning `Promise<any>` (the created record, including `id`). Also `generatedName(entity: string): string`. Fixture `seed: Seeder`.

- [ ] **Step 1: Write the failing test — `e2e/tests/seeded/seed-fixture.spec.ts`**

```ts
import { test, expect } from '../../fixtures';

test('seeded channel is retrievable and namespaced', async ({ api, seed }) => {
  const channel = await seed.channel();

  expect(channel.id).toBeTruthy();
  expect(channel.name).toMatch(/^e2e-w\d+-/);

  const res = await api.get(`/api/channels/channels/${channel.id}/`);
  expect(res.status()).toBe(200);
  expect((await res.json()).name).toBe(channel.name);
});

test('seeded names are unique within a test', async ({ seed }) => {
  const a = await seed.channel();
  const b = await seed.channel();
  expect(a.name).not.toBe(b.name);
});

test('overrides are applied', async ({ seed }) => {
  const profile = await seed.channelProfile();
  expect(profile.name).toMatch(/channelProfile/);

  const user = await seed.user({ user_level: 1 });
  expect(user.user_level).toBe(1);
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd e2e && npm run test:seeded -- seed-fixture`
Expected: FAIL — `seed` is not a known fixture.

- [ ] **Step 3: Write `e2e/fixtures/seed.ts`**

```ts
import type { ApiClient } from './api';

/** Usernames are validated against ^[A-Za-z0-9._@-]+$ — keep names in that set. */
function sanitise(value: string): string {
  return value.replace(/[^A-Za-z0-9._@-]/g, '-');
}

/**
 * Creates entities through the REST API with generated, worker-scoped names.
 *
 * Callers cannot pass a name: the shared instance is never empty, and a
 * hand-picked name is how two parallel workers collide. Assertions must
 * filter on the generated name, never on a global count.
 */
export class Seeder {
  private counter = 0;

  constructor(
    private api: ApiClient,
    private workerIndex: number,
    private testId: string
  ) {}

  generatedName(entity: string): string {
    return sanitise(
      `e2e-w${this.workerIndex}-${this.testId}-${entity}-${this.counter++}`
    );
  }

  private async create(url: string, entity: string, body: object) {
    const res = await this.api.post(url, body);
    return this.api.json(res, `seed.${entity}`);
  }

  channel(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/channels/', 'channel', {
      name: this.generatedName('channel'),
      ...overrides,
    });
  }

  user(overrides: Record<string, unknown> = {}) {
    const username = this.generatedName('user');
    return this.create('/api/accounts/users/', 'user', {
      username,
      password: 'Seeded-Password-42!',
      email: `${username}@example.com`,
      user_level: 1,
      ...overrides,
    });
  }

  channelProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/channels/profiles/', 'channelProfile', {
      name: this.generatedName('channelProfile'),
      ...overrides,
    });
  }

  streamProfile(overrides: Record<string, unknown> = {}) {
    return this.create('/api/core/streamprofiles/', 'streamProfile', {
      name: this.generatedName('streamProfile'),
      command: 'ffmpeg',
      parameters: '-i {streamUrl} -c copy -f mpegts pipe:1',
      is_active: true,
      ...overrides,
    });
  }

  m3uAccount(overrides: Record<string, unknown> = {}) {
    return this.create('/api/m3u/accounts/', 'm3uAccount', {
      name: this.generatedName('m3uAccount'),
      server_url: 'http://127.0.0.1:9/playlist.m3u',
      is_active: false,
      ...overrides,
    });
  }

  epgSource(overrides: Record<string, unknown> = {}) {
    return this.create('/api/epg/sources/', 'epgSource', {
      name: this.generatedName('epgSource'),
      source_type: 'xmltv',
      url: 'http://127.0.0.1:9/xmltv.xml',
      is_active: false,
      ...overrides,
    });
  }
}
```

`m3uAccount` and `epgSource` default to `is_active: false` and a dead-port URL so seeding never kicks off a background refresh against a real network. G3 overrides both once G2's provider exists.

- [ ] **Step 4: Register the fixture in `e2e/fixtures/index.ts`**

Replace the file with:

```ts
import { test as base } from '@playwright/test';
import { ApiClient } from './api';
import { Seeder } from './seed';

export type Fixtures = {
  api: ApiClient;
  seed: Seeder;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new ApiClient(request));
  },
  seed: async ({ api }, use, testInfo) => {
    await use(new Seeder(api, testInfo.workerIndex, testInfo.testId));
  },
});

export { expect } from '@playwright/test';
export { ApiClient } from './api';
export { Seeder } from './seed';
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e && npm run test:seeded -- seed-fixture`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add e2e/fixtures e2e/tests/seeded/seed-fixture.spec.ts
git commit -m "test(e2e): add seed fixture with unbypassable name namespacing

Names are generated from testInfo.workerIndex and testId; callers cannot
pass one. Playwright hands a restarted worker a fresh workerIndex, so a
retry cannot collide with its own leaked data.

M3U accounts and EPG sources seed inactive against a dead port so creating
one never triggers a background refresh."
```

---

### Task 5: `asUser` fixture and the authorization exemplar

The REST API is deny-by-default on `user_level` (Streamer 0 / Standard 1 / Admin 10). Wave 2's G5 needs to drive non-admin contexts.

**Files:**
- Create: `e2e/fixtures/auth.ts`
- Modify: `e2e/fixtures/index.ts`
- Create: `e2e/tests/seeded/authorization.spec.ts`

**Interfaces:**
- Consumes: `ApiClient`, `Seeder`.
- Produces: `asUser(username, password): Promise<ApiClient>` — an `ApiClient` authenticated as that user. Fixtures `asUser` and `adminPage`.

- [ ] **Step 1: Write the failing test — `e2e/tests/seeded/authorization.spec.ts`**

```ts
import { test, expect } from '../../fixtures';

// Exemplar: how wave 2 drives a non-admin principal. The REST API is
// deny-by-default (DEFAULT_PERMISSION_CLASSES = IsAdmin), so a Standard user
// is refused admin surfaces unless the view opts down.
test('a Standard user cannot list users', async ({ seed, asUser }) => {
  const user = await seed.user({ user_level: 1 });

  const client = await asUser(user.username, 'Seeded-Password-42!');
  const res = await client.get('/api/accounts/users/');

  expect([401, 403]).toContain(res.status());
});

test('an admin can list users', async ({ api }) => {
  const res = await api.get('/api/accounts/users/');
  expect(res.status()).toBe(200);
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd e2e && npm run test:seeded -- authorization`
Expected: FAIL — `asUser` is not a known fixture.

- [ ] **Step 3: Write `e2e/fixtures/auth.ts`**

```ts
import type { APIRequestContext } from '@playwright/test';
import { ApiClient } from './api';

/**
 * An ApiClient authenticated as an arbitrary user rather than the bootstrap
 * admin. Tokens are held in memory; nothing is written to the auth files.
 */
export async function makeUserClient(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<ApiClient> {
  const res = await ctx.post('/api/accounts/token/', {
    data: { username, password },
  });
  if (!res.ok()) {
    throw new Error(
      `login as ${username} failed: ${res.status()} ${await res.text()}`
    );
  }
  const { access, refresh } = await res.json();

  const client = new ApiClient(ctx);
  client.useTokens({ access, refresh });
  return client;
}
```

- [ ] **Step 4: Add `useTokens` to `ApiClient` in `e2e/fixtures/api.ts`**

Insert immediately after `expireAccessTokenForTest`:

```ts
  /** Re-point this client at a different principal's tokens. */
  useTokens(tokens: { access: string; refresh: string }): void {
    this.tokens = { ...this.tokens, ...tokens };
  }
```

- [ ] **Step 5: Register the fixture in `e2e/fixtures/index.ts`**

Add to the `Fixtures` type:

```ts
  asUser: (username: string, password: string) => Promise<ApiClient>;
  adminPage: Page;
```

Add to `base.extend`:

```ts
  asUser: async ({ request }, use) => {
    await use((username: string, password: string) =>
      makeUserClient(request, username, password)
    );
  },
  // The seeded project already applies the admin storageState to `page`, so
  // this is an alias. It exists because the fixture contract names it, and
  // because a spec that says `adminPage` states its intent — a later project
  // could hand `page` a different principal without touching the tests.
  adminPage: async ({ page }, use) => {
    await use(page);
  },
```

Add `import type { Page } from '@playwright/test';`, the import
`import { makeUserClient } from './auth';`, and re-export `makeUserClient`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd e2e && npm run test:seeded -- authorization`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add e2e/fixtures e2e/tests/seeded/authorization.spec.ts
git commit -m "test(e2e): add asUser fixture and the authorization exemplar

The REST API is deny-by-default on user_level, so G5's authorization matrix
needs non-admin principals. asUser mints tokens in memory without touching
the bootstrap auth files."
```

---

### Task 6: `waitFor` and `ws` fixtures, and the async exemplar

Background work returns 200 immediately and completes later, announced on `/ws/`.

**Files:**
- Create: `e2e/fixtures/wait.ts`, `e2e/fixtures/ws.ts`
- Modify: `e2e/fixtures/index.ts`, `e2e/package.json`
- Create: `e2e/tests/seeded/async-wait.spec.ts`

**Interfaces:**
- Consumes: `ApiClient`, `Seeder`.
- Produces: `waitFor.condition(fn, opts?)`, `waitFor.resource(url, predicate, opts?)`; `class WsListener` with `waitForMessage(type, timeoutMs?)` and `close()`. Fixtures `waitFor`, `ws`.

- [ ] **Step 1: Add the WebSocket client dependency**

```bash
cd e2e && npm install --save-dev ws@8.18.0 @types/ws@8.5.13
```

- [ ] **Step 2: Write the failing test — `e2e/tests/seeded/async-wait.spec.ts`**

```ts
import { test, expect } from '../../fixtures';

// Exemplar: polling is the default way to wait for backend state. Prefer it
// over the WebSocket unless the state is only observable there.
test('waitFor.resource polls until a created channel appears', async ({
  api,
  seed,
  waitFor,
}) => {
  const channel = await seed.channel();

  const found = await waitFor.resource(
    `/api/channels/channels/${channel.id}/`,
    (body) => body.name === channel.name
  );

  expect(found.id).toBe(channel.id);
});

// Exemplar: the WebSocket fixture, for state the REST API does not expose.
// Every socket receives connection_established on connect.
test('ws fixture receives the connection handshake', async ({ ws }) => {
  const message = await ws.waitForMessage('connection_established');
  expect(message.data.success).toBe(true);
});
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `cd e2e && npm run test:seeded -- async-wait`
Expected: FAIL — `waitFor` and `ws` are not known fixtures.

- [ ] **Step 4: Write `e2e/fixtures/wait.ts`**

```ts
import type { ApiClient } from './api';

export type WaitOptions = {
  timeoutMs?: number;
  intervalMs?: number;
  description?: string;
};

/**
 * REST polling. The default way to wait for Celery-backed work: the HTTP call
 * that triggers it returns 200 immediately and completes much later.
 */
export class Waiter {
  constructor(private api: ApiClient) {}

  async condition(
    predicate: () => Promise<boolean>,
    { timeoutMs = 60_000, intervalMs = 1_000, description = 'condition' }: WaitOptions = {}
  ): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    let lastError: unknown;

    while (Date.now() < deadline) {
      try {
        if (await predicate()) return;
      } catch (error) {
        lastError = error;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    throw new Error(
      `timed out after ${timeoutMs}ms waiting for ${description}` +
        (lastError ? ` (last error: ${lastError})` : '')
    );
  }

  async resource<T = any>(
    url: string,
    predicate: (body: T) => boolean,
    options: WaitOptions = {}
  ): Promise<T> {
    let latest: T | undefined;

    await this.condition(
      async () => {
        const res = await this.api.get(url);
        if (!res.ok()) return false;
        latest = await res.json();
        return predicate(latest as T);
      },
      { description: `${url} to satisfy predicate`, ...options }
    );

    return latest as T;
  }

  /** An M3U account whose most recent refresh has finished. */
  async m3uRefreshComplete(accountId: number, options: WaitOptions = {}) {
    return this.resource(
      `/api/m3u/accounts/${accountId}/`,
      (body: any) => body.status !== 'fetching' && body.status !== 'parsing',
      { description: `M3U account ${accountId} refresh`, timeoutMs: 180_000, ...options }
    );
  }
}
```

- [ ] **Step 5: Write `e2e/fixtures/ws.ts`**

```ts
import WebSocket from 'ws';
import fs from 'node:fs';

const TOKENS_FILE = 'playwright/.auth/tokens.json';

/**
 * Subscription to the single `updates` group on /ws/.
 *
 * Auth is a `token` query parameter carrying the access JWT
 * (dispatcharr/jwt_ws_auth.py); an unauthenticated socket is closed
 * immediately. Use this only for state the REST API does not expose — the
 * message vocabulary is a fixed dict in the product and will drift.
 */
export class WsListener {
  private socket: WebSocket;
  private received: any[] = [];
  private waiters: Array<{ type: string; resolve: (message: any) => void }> = [];

  constructor(baseURL: string) {
    const { access } = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
    const url = new URL(baseURL);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/';
    url.searchParams.set('token', access);

    this.socket = new WebSocket(url.toString());
    this.socket.on('message', (raw) => {
      const message = JSON.parse(raw.toString());
      this.received.push(message);
      const index = this.waiters.findIndex((w) => w.type === message.type);
      if (index >= 0) this.waiters.splice(index, 1)[0].resolve(message);
    });
  }

  waitForMessage(type: string, timeoutMs = 30_000): Promise<any> {
    const already = this.received.find((m) => m.type === type);
    if (already) return Promise.resolve(already);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`timed out waiting for ws message '${type}'`)),
        timeoutMs
      );
      this.waiters.push({
        type,
        resolve: (message) => {
          clearTimeout(timer);
          resolve(message);
        },
      });
    });
  }

  close(): void {
    this.socket.close();
  }
}
```

- [ ] **Step 6: Register both fixtures in `e2e/fixtures/index.ts`**

Add to `Fixtures`:

```ts
  waitFor: Waiter;
  ws: WsListener;
```

Add to `base.extend`:

```ts
  waitFor: async ({ api }, use) => {
    await use(new Waiter(api));
  },
  ws: async ({ baseURL }, use) => {
    const listener = new WsListener(baseURL!);
    await use(listener);
    listener.close();
  },
```

Add imports for `Waiter` and `WsListener` and re-export both.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd e2e && npm run test:seeded -- async-wait`
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add e2e/fixtures e2e/tests/seeded/async-wait.spec.ts e2e/package.json e2e/package-lock.json
git commit -m "test(e2e): add waitFor polling and ws subscription fixtures

Celery-backed work returns 200 immediately and finishes minutes later,
announced over /ws/. Polling is the default because the WebSocket message
vocabulary is a fixed dict in the product and will drift; the ws fixture
exists for state the REST API does not expose.

WebSocket auth is a token query parameter — jwt_ws_auth.py closes any socket
that arrives without one."
```

---

### Task 7: `streamClient` fixture, throwaway upstream, streaming exemplar

Playwright's `request` fixture cannot read `/proxy/ts/stream/<uuid>`: `APIResponse.body()` awaits full download, and that endpoint never ends. This uses Node `fetch` over a `ReadableStream`.

The static upstream here is **throwaway** — G2 replaces it. Its only job is to prove the fixture works before G4 depends on it.

**Files:**
- Create: `e2e/fixtures/stream-client.ts`, `e2e/support/static-upstream.ts`
- Modify: `e2e/fixtures/index.ts`
- Create: `e2e/tests/streaming/stream-client.spec.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (deliberately standalone).
- Produces: `class StreamClient` with `open(path)`, `readPackets(n)`, `collectFor(ms)`, `close()`; `expectTsAligned(buffer)`; `startStaticUpstream(port)` → `{ url, close() }`. Fixture `streamClient`.

- [ ] **Step 1: Write the failing test — `e2e/tests/streaming/stream-client.spec.ts`**

```ts
import { test, expect, expectTsAligned } from '../../fixtures';
import { startStaticUpstream } from '../../support/static-upstream';

// Exemplar: byte-level assertions against an endless stream. Playwright's
// request fixture cannot do this — APIResponse.body() awaits full download
// and a live stream never finishes.
//
// The upstream here is throwaway scaffolding, replaced by G2's fake provider.
test('streamClient reads aligned TS packets from an endless stream', async ({
  streamClient,
}) => {
  const upstream = await startStaticUpstream(9401);

  try {
    await streamClient.open(`${upstream.url}/loop.ts`);

    const packets = await streamClient.readPackets(20);
    expect(packets.length).toBe(20 * 188);
    expectTsAligned(packets);

    const collected = await streamClient.collectFor(1_000);
    expect(collected.byteLength).toBeGreaterThan(0);
  } finally {
    await streamClient.close();
    await upstream.close();
  }
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd e2e && npm run test:streaming`
Expected: FAIL — `Cannot find module '../../support/static-upstream'`.

- [ ] **Step 3: Write `e2e/support/static-upstream.ts`**

```ts
import http from 'node:http';

const TS_PACKET_SIZE = 188;
const SYNC_BYTE = 0x47;

/**
 * THROWAWAY. A minimal endless MPEG-TS source, here only so streamClient has
 * something real to read before G2's fake provider exists. Delete this file
 * when G2 lands.
 *
 * Emits well-formed 188-byte packets on PID 0x0100 with an incrementing
 * continuity counter, so alignment assertions are meaningful.
 */
function makePacket(counter: number): Buffer {
  const packet = Buffer.alloc(TS_PACKET_SIZE, 0xff);
  packet[0] = SYNC_BYTE;
  packet[1] = 0x01; // PID high bits
  packet[2] = 0x00; // PID low bits
  packet[3] = 0x10 | (counter % 16); // payload only + continuity counter
  return packet;
}

export async function startStaticUpstream(port: number) {
  let counter = 0;

  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'video/mp2t' });
    const timer = setInterval(() => {
      const burst = Buffer.concat(
        Array.from({ length: 10 }, () => makePacket(counter++))
      );
      if (!res.write(burst)) return;
    }, 20);
    res.on('close', () => clearInterval(timer));
  });

  await new Promise<void>((resolve) => server.listen(port, '127.0.0.1', resolve));

  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
```

- [ ] **Step 4: Write `e2e/fixtures/stream-client.ts`**

```ts
import { expect } from '@playwright/test';

export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;

/**
 * Asserts a buffer is 188-byte-aligned MPEG-TS: every packet boundary carries
 * the 0x47 sync byte. apps/proxy/live_proxy/input/buffer.py realigns to this
 * before writing chunks, so a misaligned read is a real defect.
 */
export function expectTsAligned(buffer: Buffer): void {
  expect(
    buffer.byteLength % TS_PACKET_SIZE,
    `buffer of ${buffer.byteLength} bytes is not a whole number of 188-byte packets`
  ).toBe(0);

  for (let offset = 0; offset < buffer.byteLength; offset += TS_PACKET_SIZE) {
    expect(
      buffer[offset],
      `expected sync byte 0x47 at offset ${offset}, got 0x${buffer[offset].toString(16)}`
    ).toBe(TS_SYNC_BYTE);
  }
}

/**
 * Reads endless HTTP byte streams. Node fetch, not Playwright's request
 * fixture: APIResponse.body() returns Promise<Buffer> and internally awaits
 * the full download, so it never resolves against /proxy/ts/stream/<uuid>.
 */
export class StreamClient {
  private controller?: AbortController;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private buffered: Buffer = Buffer.alloc(0);

  constructor(private baseURL: string) {}

  /** `path` may be absolute or relative to baseURL. */
  async open(path: string, headers: Record<string, string> = {}): Promise<void> {
    this.controller = new AbortController();
    const url = path.startsWith('http') ? path : new URL(path, this.baseURL).toString();

    const response = await fetch(url, {
      headers,
      signal: this.controller.signal,
    });
    if (!response.ok) {
      throw new Error(`stream open failed: ${response.status} ${response.statusText}`);
    }
    if (!response.body) {
      throw new Error('stream response carried no body');
    }
    this.reader = response.body.getReader();
  }

  private async pump(): Promise<boolean> {
    if (!this.reader) throw new Error('open() must be called before reading');
    const { done, value } = await this.reader.read();
    if (done) return false;
    this.buffered = Buffer.concat([this.buffered, Buffer.from(value)]);
    return true;
  }

  /** Exactly `count` TS packets (count * 188 bytes). */
  async readPackets(count: number): Promise<Buffer> {
    const wanted = count * TS_PACKET_SIZE;
    while (this.buffered.byteLength < wanted) {
      if (!(await this.pump())) {
        throw new Error(
          `stream ended after ${this.buffered.byteLength} bytes, wanted ${wanted}`
        );
      }
    }
    const out = this.buffered.subarray(0, wanted);
    this.buffered = this.buffered.subarray(wanted);
    return Buffer.from(out);
  }

  /** Everything that arrives within `ms`. */
  async collectFor(ms: number): Promise<Buffer> {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      const remaining = deadline - Date.now();
      const timed = await Promise.race([
        this.pump(),
        new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), remaining)),
      ]);
      if (timed === 'timeout' || timed === false) break;
    }
    const out = this.buffered;
    this.buffered = Buffer.alloc(0);
    return out;
  }

  async close(): Promise<void> {
    this.controller?.abort();
    this.reader = undefined;
    this.buffered = Buffer.alloc(0);
  }
}
```

- [ ] **Step 5: Register the fixture in `e2e/fixtures/index.ts`**

Add to `Fixtures`:

```ts
  streamClient: StreamClient;
```

Add to `base.extend`:

```ts
  streamClient: async ({ baseURL }, use) => {
    const client = new StreamClient(baseURL!);
    await use(client);
    await client.close();
  },
```

Add the import and re-export `StreamClient`, `expectTsAligned`, `TS_PACKET_SIZE`, `TS_SYNC_BYTE`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd e2e && npm run test:streaming`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add e2e/fixtures e2e/support e2e/tests/streaming
git commit -m "test(e2e): add Node-fetch streamClient with TS packet helpers

Playwright's request fixture cannot read the proxy: APIResponse.body()
returns Promise<Buffer> and awaits the full download, so it never resolves
against an endpoint designed never to end. streamClient uses Node fetch over
a ReadableStream with an AbortController.

readPackets/collectFor/expectTsAligned live here rather than in G4 so the
188-byte alignment logic is written once.

e2e/support/static-upstream.ts is throwaway scaffolding to prove the fixture
works before G2's fake provider exists. G2 deletes it."
```

---

### Task 8: Glossary, coverage inventory, README, ADR

**Files:**
- Create: `CONTEXT.md`, `e2e/COVERAGE.md`, `e2e/README.md`, `docs/adr/0001-e2e-shared-api-seeded-container.md`

**Interfaces:**
- Consumes: everything built so far (documents it).
- Produces: the documents wave-2 agents read before writing a line.

- [ ] **Step 1: Write `CONTEXT.md` at the repo root**

Glossary only — no implementation detail, no spec content.

```markdown
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
```

- [ ] **Step 2: Write `e2e/COVERAGE.md`**

```markdown
# E2E Coverage Inventory

The shared worklist for all seven goals. **Update this in the same PR as the
tests.** Status: `todo` / `done` / `known-bug` (asserted correct, marked
`test.fail()`, issue filed).

| Area | Flow | Goal | Status |
|---|---|---|---|
| Setup | First-run superuser creation and login | G1 | done |
| Harness | Authenticated session via storageState | G1 | done |
| Harness | API client survives token expiry | G1 | done |
| Harness | Namespaced seeding | G1 | done |
| Harness | Non-admin principal (asUser) | G1 | done |
| Harness | REST polling and WebSocket waiting | G1 | done |
| Harness | Byte-level TS stream reading | G1 | done |
| Sources | M3U account create → refresh → streams appear | G3 | todo |
| Sources | EPG source create → refresh → programme data | G3 | todo |
| Sources | Channel creation from streams | G3 | todo |
| Sources | Auto channel sync | G3 | todo |
| Sources | Channel groups and Channel Profiles | G3 | todo |
| Sources | Logo upload and assignment | G3 | todo |
| Streaming | Single client receives aligned TS | G4 | todo |
| Streaming | N clients share one upstream | G4 | todo |
| Streaming | Mid-stream switch does not disturb clients | G4 | todo |
| Streaming | Failover: dead air | G4 | todo |
| Streaming | Failover: connect failure | G4 | todo |
| Streaming | Failover: buffering (ffmpeg only) | G4 | todo |
| Streaming | Client teardown releases the upstream | G4 | todo |
| Streaming | Stream Profile: Redirect / Proxy / FFmpeg | G4 | todo |
| Streaming | Output Profile shared per (channel, profile) | G4 | todo |
| Output | /output/m3u parses and every URL streams | G5 | todo |
| Output | /output/epg is valid XMLTV | G5 | todo |
| Output | HDHomeRun discovery and lineup | G5 | todo |
| Output | Xtream player_api actions | G5 | todo |
| Output | Catch-up / timeshift URLs | G5 | todo |
| Output | Authorization matrix by user_level | G5 | todo |
| Output | hide_adult_content across all listing paths | G5 | todo |
| Frontend | Guide grid renders and navigates | G6 | todo |
| Frontend | DVR: schedule, list, cancel a recording | G6 | todo |
| Frontend | Users: create, edit, delete | G6 | todo |
| Frontend | Settings: change and persist | G6 | todo |
| Frontend | Plugins: list, enable, configure | G6 | todo |
| Frontend | Stats page renders live data | G6 | todo |
| Frontend | Connect: webhook CRUD | G6 | todo |
| Frontend | Logos: upload and browse | G6 | todo |
| Frontend | Backups: create and restore | G6 | todo |
| Lifecycle | Upgrade from previous release (migrations) | G7 | todo |
| Lifecycle | Restart preserves channels and settings | G7 | todo |
| Lifecycle | PUID/PGID honoured | G7 | todo |
| Lifecycle | TLS Postgres connection | G7 | todo |
```

- [ ] **Step 3: Write `e2e/README.md`**

````markdown
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

## Running against an existing instance

```bash
E2E_BASE_URL=http://my-box:9191 npm run test:seeded
```

`bootstrap` POSTs to `/api/accounts/initialize-superuser/`, which is IP-gated
to private/loopback addresses (`dispatcharr/utils.py:142`). Against a public
instance, set `DISPATCHARR_SETUP_ALLOWED_IP` on that instance first.

## Writing a test

1. Read the root `CONTEXT.md`. Three different things are called "profile".
2. Import from `../../fixtures`, never `@playwright/test` directly.
3. Seed what you need; never assume the instance is empty.
4. Never assert a global count, an unfiltered list, or a notification toast.
5. Update `COVERAGE.md` in the same PR.
6. Found a product bug? Assert the *correct* behaviour, mark it
   `test.fail()`, and run
   `gh issue create --repo D10Scot/Dispatcharr`. Do not patch the product.

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
````

- [ ] **Step 4: Write `docs/adr/0001-e2e-shared-api-seeded-container.md`**

```markdown
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
with the Playwright worker index.

Populations that genuinely cannot share an instance — first-run setup, global
settings, migrations, PUID/PGID, TLS Postgres — run in a separate `pristine`
project against their own container.

## Consequences

- No test may assert on a global count or an unfiltered list. The instance is
  never empty. This is the constraint that most often bites.
- Seed helpers generate names and refuse caller-supplied ones, so namespacing
  cannot be forgotten.
- No cleanup: the container is destroyed with the job, and cascade-delete
  ordering across Channel/Stream/ChannelProfile is a flake source that masks
  real assertions.
- Anything needing a pristine instance must go to the `pristine` project. That
  project is not optional overhead; it is where those tests live.
- Reversing this later means rewriting every assertion that filters by prefix.
```

- [ ] **Step 5: Verify the docs are internally consistent**

Run: `cd e2e && npm run test:seeded && npm run test:streaming`
Expected: all pass. Then confirm every `done` row in `COVERAGE.md` corresponds to a spec file that exists:

```bash
ls e2e/tests/seeded e2e/tests/streaming e2e/tests/pristine
```

- [ ] **Step 6: Commit**

```bash
git add CONTEXT.md e2e/COVERAGE.md e2e/README.md docs/adr
git commit -m "docs(e2e): add glossary, coverage inventory, README and ADR

CONTEXT.md is a glossary, not a spec. It exists because three distinct
concepts in this codebase are called 'profile' and 'stream' means both a
model row and an activity — the exact ambiguity five parallel agents would
otherwise resolve five different ways.

COVERAGE.md is the shared worklist across all seven goals; it lists what does
not exist yet, which is why it is hand-maintained rather than generated."
```

---

### Task 9: CI workflow — one build, three consumers

**Files:**
- Modify: `.github/workflows/e2e-tests.yml`

**Interfaces:**
- Consumes: npm scripts and project names from Task 1; `scripts/e2e_up.sh` is *not* used in CI (the workflow runs docker directly so the built image is the artifact under test).
- Produces: jobs `build`, `pristine`, `seeded`, `streaming`.

**Note:** editing this file triggers the repo's zizmor hook, which blocks on **every** finding. Keep `permissions: contents: read` at the top level, `persist-credentials: false` on every checkout, and full 40-character SHA pins with a version comment. Reuse the SHAs already in this file rather than resolving new ones.

- [ ] **Step 1: Replace `.github/workflows/e2e-tests.yml`**

```yaml
name: E2E Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: e2e-tests-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    name: Build AIO image
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      # One build for all three consumers. docker/Dockerfile:14 uses
      # `npm install` with no lockfile, so N builds can produce N different
      # frontend bundles; building once means one artifact under test.
      - name: Build the image
        run: docker build -f docker/Dockerfile -t dispatcharr-e2e:local .

      - name: Export the image
        run: docker save dispatcharr-e2e:local | gzip > /tmp/dispatcharr-e2e.tar.gz

      - name: Upload the image
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: dispatcharr-e2e-image
          path: /tmp/dispatcharr-e2e.tar.gz
          retention-days: 1

  test:
    name: ${{ matrix.project }}
    runs-on: ubuntu-latest
    needs: build
    strategy:
      fail-fast: false
      matrix:
        project: [pristine, seeded, streaming]
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Download the image
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with:
          name: dispatcharr-e2e-image
          path: /tmp

      - name: Load the image
        run: docker load < /tmp/dispatcharr-e2e.tar.gz

      # Each project gets its own container. pristine in particular needs an
      # instance with no superuser, which the bootstrap project consumes.
      - name: Run the container
        run: |
          docker run -d --name dispatcharr-e2e \
            -p 9191:9191 \
            -v dispatcharr-e2e-data:/data \
            -e DISPATCHARR_ENV=aio \
            -e DISPATCHARR_LOG_LEVEL=info \
            dispatcharr-e2e:local

      - name: Wait for the app to be ready
        run: |
          for i in $(seq 1 60); do
            if curl -sf -o /dev/null "http://localhost:9191/api/accounts/initialize-superuser/"; then
              echo "App is up after ${i}0s"
              exit 0
            fi
            sleep 10
          done
          echo "App never became ready; container logs:"
          docker logs dispatcharr-e2e || true
          exit 1

      - name: Setup Node.js
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: '24'

      - name: Install E2E dependencies
        working-directory: ./e2e
        run: npm ci

      - name: Install Playwright browsers
        working-directory: ./e2e
        run: npx playwright install --with-deps chromium

      - name: Typecheck
        working-directory: ./e2e
        run: npm run typecheck

      - name: Run E2E tests
        working-directory: ./e2e
        env:
          E2E_BASE_URL: http://localhost:9191
        run: npx playwright test --project=${{ matrix.project }}

      - name: Container logs (on failure)
        if: failure()
        run: docker logs dispatcharr-e2e || true

      - name: Upload Playwright report
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: playwright-report-${{ matrix.project }}
          path: e2e/playwright-report/
          retention-days: 7
          if-no-files-found: ignore

      - name: Stop the container
        if: always()
        run: docker rm -f dispatcharr-e2e || true
```

- [ ] **Step 2: Confirm the download-artifact SHA**

The `actions/download-artifact` pin above is the only action not already in this repo's workflows. Verify it before committing:

```bash
gh api repos/actions/download-artifact/commits/v4.3.0 --jq .sha
```

Expected: matches `d3f86a106a0bac45b974a628896c90dbdf5c8093`. If it does not, use the command's output — a SHA that is not the literal output of a resolution command is not a valid pin.

- [ ] **Step 3: Run zizmor locally**

Run: `zizmor .github/workflows/e2e-tests.yml`
Expected: no findings. The PostToolUse hook enforces this on save; CI enforces it in `actions-lint.yml`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/e2e-tests.yml
git commit -m "ci(e2e): one build, three project jobs

Splits the E2E workflow into a build job that exports the image as an
artifact and a matrix of three consumers, each with its own container.
pristine needs an instance with no superuser, which bootstrap consumes, so it
cannot share with seeded.

Building once matters for correctness, not just speed: docker/Dockerfile:14
uses npm install with no lockfile, so parallel builds can ship different
frontend bundles and produce job-specific failures that are not real."
```

- [ ] **Step 5: Push and confirm CI is green**

```bash
git push -u origin HEAD
gh pr create --repo D10Scot/Dispatcharr --fill
gh pr checks --repo D10Scot/Dispatcharr --watch
```

Expected: `build`, `pristine`, `seeded`, `streaming` all pass.

---

## Post-plan: human step

D9 in the spec ("E2E required on PRs") **cannot be completed by an agent.** Required checks are a branch-protection rule on `main`, and this fork has none. After this plan merges, a human must add a rule naming `pristine`, `seeded` and `streaming`. Shipping the workflow does not satisfy D9 — do not report it as done.
