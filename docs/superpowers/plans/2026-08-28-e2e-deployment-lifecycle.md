# G7 — Deployment Lifecycle E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a Dispatcharr container survives restart, upgrade-onto-an-existing-volume, a foreign PUID/PGID, and a TLS-only PostgreSQL — by wiring up the two never-executed bash suites and writing the two Playwright specs that do not exist.

**Architecture:** Two pieces of different character. **Piece A** is a new workflow, `.github/workflows/lifecycle-tests.yml`, that runs `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` *entirely unmodified* against one shared AIO image. **Piece B** is a new `e2e/tests/lifecycle/` directory holding two Playwright specs, each owning its container's lifecycle through a new `instance` fixture that wraps `scripts/e2e_up.sh`. The restart spec joins `e2e-tests.yml`'s matrix; the ~9-minute upgrade spec runs in `lifecycle-tests.yml` beside Piece A, reusing the AIO image that workflow already builds.

**Tech Stack:** Playwright 1.62.1 + TypeScript 5.7.2 (ESM, `moduleResolution: bundler`, `strict`), Node 24, Bash, GitHub Actions, Docker.

**Spec:** `docs/superpowers/specs/2026-08-28-e2e-deployment-lifecycle-design.md` — read it. Decisions are cited below as **D1**–**D16** and the spec's rationale is not repeated here.

---

## Global Constraints

Copied verbatim in substance from the spec and from `CLAUDE.md`. Every task's requirements implicitly include this section.

1. **The bash suites are not modified. Not one line.** (D2) `docker/tests/test-puid-pgid.sh` and `docker/tests/test-tls-postgres.sh` are known-good and have never run; changing them in the PR that first executes them destroys the only signal the PR carries. Two live temptations to resist: `RELEASE_IMAGE` pointing at **upstream's** `ghcr.io/dispatcharr/dispatcharr:latest` is *correct* (those scenarios simulate upgrading from the published pre-PUID image), and the unused `BASE_IMAGE` variable is cosmetic. If a suite proves broken, that is a follow-up PR that says so.
2. **`--keep-on-fail` is never passed.** (D7) The TLS suite reuses `tls_test_app`/`tls_test_pg`/`tls_test_redis` across all 8 scenarios, so keeping one failure's containers turns the next `docker run --name` into a cascade of six fabricated failures; the puid suite's keep-branch is run-global and accumulates up to 20 containers plus PostgreSQL data volumes.
3. **Product defects are asserted correct, marked `test.fail()` with a comment naming the defect, and filed** — never patched. (D15) `gh issue create --repo D10Scot/Dispatcharr`. **The `--repo` flag is mandatory**: this checkout is a fork of `Dispatcharr/Dispatcharr` and `gh` without it files on upstream's public tracker.
4. **Assert Postgres-backed state only.** (D11) Redis has no persistence in AIO and `scripts/wait_for_redis.py` calls `flushdb()` on every boot. A Redis-backed persistence assertion asserts a falsehood.
5. **Never assert on a global count or an unfiltered list.** Roadmap rule 4. Assert by id, with values recorded at creation.
6. **Every `uses:` in a workflow is a full 40-character commit SHA with a trailing version comment.** Every `actions/checkout` gets `persist-credentials: false`. `permissions: contents: read` at the top level and nowhere else. The zizmor hook blocks on **every** finding in an edited workflow file, legacy included, and the workflows are currently at zero findings — a ratchet.
7. **Reuse the action pins already in `.github/workflows/e2e-tests.yml`** rather than resolving new ones. They are, verbatim:
   - `actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0`
   - `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2`
   - `actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0`
   - `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0`
8. **Typecheck is `cd e2e && npm run typecheck`.** `npx tsc --noEmit -p e2e` from the repo root does not resolve — there is no root-level typescript. The `PostToolUse` hook runs it on every `e2e/**/*.ts` edit and blocks.
9. **`e2e/COVERAGE.md` is updated in the same PR as the tests.** Roadmap rule 3.
10. **Read the root `CONTEXT.md` before naming anything.** Three distinct things are called "profile" (Stream Profile, Output Profile, Channel Profile).
11. **Do not touch `CLAUDE.md`.** Spec non-goal: the stale `docker-build.yml` claim is a follow-up, not an edit inside this PR.

## Reconciliation with `main` — rulings made before this plan was written

`main` moved three times under the G7 spec (#30, #35, #37). These are settled; do not re-derive them.

| # | Ruling | Cost if wrong |
|---|---|---|
| **G7-R1** | `e2e-tests.yml` is now `changes` → (`build`, `upstream`) → `test` (matrix) → `e2e-result`. **D14 is unchanged in substance**: adding `lifecycle` is still one entry in `matrix.project`. `e2e-result` depends on the `test` job as a whole, so a new matrix entry needs no edit there. The `changes` job's path regex already covers `e2e/`, `docker/` and `scripts/`. | The lifecycle job runs when it shouldn't, or the merge gate misreports — visible on the first PR run. |
| **G7-R2** | **`lifecycle-tests.yml` keeps D4's path-filtered triggers.** `e2e-tests.yml` always triggers on PRs *only because* a branch ruleset requires its checks and a path-filtered workflow leaves them "Expected" forever. `lifecycle-tests.yml` is deliberately **not** a required check, so the always-trigger pattern buys nothing and costs an AIO build per PR. A comment in the file must say this. | If someone later makes a lifecycle check required, the merge gate wedges. The comment is the guard. |
| **G7-R3** | **The `lifecycle` matrix job keeps `e2e-tests.yml`'s job-level `scripts/e2e_up.sh` boot step.** It is harmless and useful: the script is idempotent, `instance.up()` short-circuits on the already-running container, and the container carries no superuser (the project declares no `bootstrap` dependency) — which is exactly what `provisionAdmin` requires. Do **not** add a conditional to skip it. | ~40s of duplicated boot, or a spec that finds no container. |
| **G7-R4** | **`provisionAdmin` ships as two exports, not one.** (See Task 2.) The spec's single `provisionAdmin(request, baseURL)` would make `bootstrap.setup.ts` spend a login on every run, destroying its `reusableTokens` optimisation against a 3/minute budget. `ensureSuperuser` holds the probe/guard/POST — the guard therefore still has exactly one call site, which is D13's actual requirement — and `provisionAdmin` composes it with the login. | Bootstrap burns one of three logins per minute on every run; surfaces as 429s in setup. |
| **G7-R5** | **G7 branches from `main`**, merged in at `57bbb6bd`. PR #33 (G4) is open and blocked on checks. The overlap is six files, all additive one-liners: `e2e/playwright.config.ts`, `e2e/package.json`, `e2e/fixtures/index.ts`, `e2e/COVERAGE.md`, `e2e/README.md`, `.github/workflows/e2e-tests.yml`. `scripts/e2e_up.sh` is **no longer** shared — G4's R17 dropped it, so G7 owns it alone. | One rebase through additive conflicts. |

---

### Task 1: `--recreate` mode for `scripts/e2e_up.sh`

Implements **D9**. An upgrade *is* "new container, same volume", and the script cannot express it: `--stop` keeps the container and therefore the image snapshot it was created from, `--reset` and `--down` destroy the volume.

**Files:**
- Modify: `scripts/e2e_up.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: `./scripts/e2e_up.sh --recreate` — removes the app container, leaves the volume, the network and the `e2e-upstream` provider container standing, then starts normally through the same boot path as a bare invocation. Honours `DISPATCHARR_E2E_IMAGE` (which is the whole point).

**Context the implementer needs:**

The script's usage text is printed by `sed`'ing the file itself: `sed -n '2,6p' "$SELF"` appears at **two** call sites — the `$# -gt 1` argument-count guard and the `*)` unknown-argument branch. Adding a usage line shifts the block, so **both `sed` ranges must be widened to `2,7p`** or the new mode is invisible in every error message. This is the one non-obvious part of the task.

The app-container reuse branches near the bottom of the script key on container **name** only, never on image id — unlike the provider, which is recreated when `UPSTREAM_IMAGE_ID` moves. That asymmetry is why `--recreate` exists and why the comment below says so.

- [ ] **Step 1: Widen the usage block and add the new line**

The header currently reads (lines 2–6):

```bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh          start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset  destroy container + volume, then start fresh
#   ./scripts/e2e_up.sh --stop   stop the container, keep it and its data
#   ./scripts/e2e_up.sh --down   destroy container + volume, start nothing
```

Replace those five lines with these six, re-aligned:

```bash
# Build and run a local Dispatcharr AIO container for E2E tests.
#   ./scripts/e2e_up.sh             start (reuse existing container if present)
#   ./scripts/e2e_up.sh --reset     destroy container + volume, then start fresh
#   ./scripts/e2e_up.sh --recreate  destroy the container, keep the volume, start fresh
#   ./scripts/e2e_up.sh --stop      stop the container, keep it and its data
#   ./scripts/e2e_up.sh --down      destroy container + volume, start nothing
```

- [ ] **Step 2: Widen both `sed` ranges from `2,6p` to `2,7p`**

Both occurrences of `sed -n '2,6p' "$SELF" >&2` become `sed -n '2,7p' "$SELF" >&2`. There are exactly two. Verify with:

```bash
grep -n "sed -n '2," scripts/e2e_up.sh
```

Expected: two lines, both `2,7p`.

- [ ] **Step 3: Add the `--recreate` case**

Insert immediately after the `--reset)` branch and before `--stop)`:

```bash
  --recreate)
    # New container, same volume. No other mode expresses an upgrade: --stop
    # keeps the container and therefore the image snapshot it was created
    # from, and --reset/--down destroy the volume the upgrade is meant to
    # carry forward.
    #
    # The volume, the network and the provider container are deliberately
    # left standing — none of them is what is being replaced, and destroy()
    # would take the provider down with them.
    #
    # Load-bearing, and the reason this mode is not optional: the app-container
    # reuse branches at the bottom of this script key on container *name*
    # only, never on image id (unlike the provider, which is recreated when
    # UPSTREAM_IMAGE_ID moves). Without this, setting DISPATCHARR_E2E_IMAGE
    # and re-running silently keeps serving the old image.
    echo "Removing container $NAME (keeping volume $VOLUME)..."
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    ;;
```

No `exit` — it falls through to the normal start path, which is the point.

- [ ] **Step 4: Verify the usage text and the argument guard**

```bash
./scripts/e2e_up.sh --rest ; echo "exit=$?"
```

Expected: `Unknown argument: --rest`, the six-line usage block **including the `--recreate` line**, and `exit=2`.

```bash
./scripts/e2e_up.sh --recreate --oops ; echo "exit=$?"
```

Expected: `Expected at most one argument, got 2`, the same six-line block, `exit=2`.

- [ ] **Step 5: Verify the mode itself against a real container**

```bash
./scripts/e2e_up.sh --reset
docker volume inspect dispatcharr-e2e-data --format '{{.CreatedAt}}'
BEFORE=$(docker inspect -f '{{.Id}}' dispatcharr-e2e)
./scripts/e2e_up.sh --recreate
AFTER=$(docker inspect -f '{{.Id}}' dispatcharr-e2e)
[ "$BEFORE" != "$AFTER" ] && echo "container replaced: OK" || echo "FAIL: same container"
docker volume inspect dispatcharr-e2e-data >/dev/null && echo "volume survived: OK"
docker ps --format '{{.Names}}' | grep -qx e2e-upstream && echo "provider survived: OK"
```

Expected: all three OK lines. If Docker is unavailable, say so explicitly in the report — do not describe this step as verified.

- [ ] **Step 6: Commit**

Stage `scripts/e2e_up.sh` only, then commit with the message:

```
feat(e2e): add --recreate to e2e_up.sh — new container, same volume
```

---

### Task 2: Extract the superuser-provisioning sequence

Implements **D13** as amended by ruling **G7-R4**. Both lifecycle specs need probe → guard → POST → login on an instance nothing has bootstrapped. Duplicating it would duplicate the superuser guard, and `e2e/setup/superuser-guard.ts`'s own header states that a guard consulted by only one of two paths is not a guard.

**Files:**
- Create: `e2e/setup/provision-admin.ts`
- Modify: `e2e/setup/bootstrap.setup.ts`

**Interfaces:**
- Consumes: `ADMIN` from `./credentials`, `assertMayCreateSuperuser` from `./superuser-guard`, `loginWithThrottleBackoff` and `TokenPair` from `./login`.
- Produces:
  - `ensureSuperuser(request: APIRequestContext, baseURL: string): Promise<void>`
  - `provisionAdmin(request: APIRequestContext, baseURL: string): Promise<TokenPair>`

**Why two functions and not the one the spec names (G7-R4):** `bootstrap.setup.ts` currently does probe/create *unconditionally* and only then `reusableTokens(request) ?? loginWithThrottleBackoff(...)`. A single `provisionAdmin` that always logs in would make bootstrap spend one of three logins a minute on **every** run, which is precisely the cost its `reusableTokens` path exists to avoid. Splitting keeps the guard at exactly one call site — D13's real requirement — while leaving bootstrap's token reuse intact.

- [ ] **Step 1: Create `e2e/setup/provision-admin.ts`**

```ts
/**
 * Creating the superuser on an instance that has never had one.
 *
 * Extracted from `bootstrap.setup.ts` so the lifecycle specs
 * (`e2e/tests/lifecycle/`) can bootstrap containers they create themselves
 * without a second copy of the sequence — and, more to the point, without a
 * second copy of `assertMayCreateSuperuser`. `superuser-guard.ts` says it
 * plainly: a guard that only one of two creation paths consults is not a
 * guard.
 *
 * Two exports rather than one, deliberately. `bootstrap` must be able to
 * ensure the superuser exists and then *reuse* a token pair from disk;
 * folding the login into the only entry point would put a standing one-login
 * cost under every bootstrap run, against a budget of three per minute for
 * the whole suite (`POST /api/accounts/token/`, DEFAULT_THROTTLE_RATES).
 */
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { ADMIN } from './credentials';
import { loginWithThrottleBackoff } from './login';
import type { TokenPair } from './login';
import { assertMayCreateSuperuser } from './superuser-guard';

/**
 * Ensure the instance at `baseURL` has the harness admin, creating it if not.
 *
 * Idempotent: `GET /api/accounts/initialize-superuser/` returns 200 whether or
 * not a superuser exists — it short-circuits to `superuser_exists: true`
 * before any method dispatch — so this is safe on a bootstrapped instance and
 * costs one request. Only `POST` is IP-gated to private/loopback
 * (`dispatcharr/utils.py`, `setup_ip_allowed`), which is why the guard runs
 * only on the create path.
 */
export async function ensureSuperuser(
  request: APIRequestContext,
  baseURL: string
): Promise<void> {
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(
    status.ok(),
    `initialize-superuser probe failed: ${status.status()} ${await status.text()}`
  ).toBeTruthy();

  const setupState: { superuser_exists?: boolean } = await status.json();
  if (setupState.superuser_exists) return;

  assertMayCreateSuperuser(baseURL);
  const created = await request.post('/api/accounts/initialize-superuser/', {
    data: ADMIN,
  });
  expect(
    created.ok(),
    `superuser creation failed: ${created.status()} ${await created.text()}`
  ).toBeTruthy();
}

/**
 * Ensure the admin exists and return a fresh token pair for it.
 *
 * For callers that own their instance's whole lifecycle and therefore cannot
 * reuse `playwright/.auth/` — a persisted pair points at a container that may
 * no longer exist. The login goes through `loginWithThrottleBackoff`, which
 * honours `Retry-After`, because it is not optional at three logins a minute.
 *
 * `bootstrap.setup.ts` deliberately does NOT call this: it calls
 * `ensureSuperuser` and then its own reuse-or-login path, so a warm run spends
 * no logins at all.
 */
export async function provisionAdmin(
  request: APIRequestContext,
  baseURL: string
): Promise<TokenPair> {
  await ensureSuperuser(request, baseURL);
  return loginWithThrottleBackoff(request, ADMIN);
}
```

- [ ] **Step 2: Rewire `bootstrap.setup.ts` to the extracted function**

In the `setup('create the superuser and persist admin auth state', …)` body, replace this block:

```ts
  const status = await request.get('/api/accounts/initialize-superuser/');
  expect(
    status.ok(),
    `initialize-superuser probe failed: ${status.status()} ${await status.text()}`
  ).toBeTruthy();

  const setupState: { superuser_exists?: boolean } = await status.json();
  if (!setupState.superuser_exists) {
    assertMayCreateSuperuser(baseURL!);
    // POST is IP-gated to private/loopback (dispatcharr/utils.py,
    // setup_ip_allowed). Fine from CI and from localhost; a public
    // E2E_BASE_URL needs DISPATCHARR_SETUP_ALLOWED_IP set on the instance —
    // read superuser-guard.ts before you do that.
    const created = await request.post('/api/accounts/initialize-superuser/', {
      data: ADMIN,
    });
    expect(
      created.ok(),
      `superuser creation failed: ${created.status()} ${await created.text()}`
    ).toBeTruthy();
  }
```

with:

```ts
  // Probe, guard and create live in ./provision-admin.ts so the lifecycle
  // specs share them — and share `assertMayCreateSuperuser` in particular.
  // The login stays here: `reusableTokens` below is what keeps a warm run at
  // zero logins, and folding it into the shared helper would spend one on
  // every bootstrap.
  await ensureSuperuser(request, baseURL!);
```

Add the import beside the existing `./superuser-guard` import:

```ts
import { ensureSuperuser } from './provision-admin';
```

Then remove the now-unused `assertMayCreateSuperuser` import. **Do not remove the `ADMIN` import** — `reusableTokens`, `loginWithThrottleBackoff` and `persistAdminAuth` all still use it. Leave `persistAdminAuth`, `prewarmIntervalSchedule`, `reusableTokens` and `provisionPrincipals` exactly as they are: they are not part of this extraction.

- [ ] **Step 3: Typecheck**

```bash
cd e2e && npm run typecheck
```

Expected: clean. An unused-import error here means Step 2's removal was incomplete or over-eager.

- [ ] **Step 4: Prove bootstrap still works, cold and warm**

```bash
./scripts/e2e_up.sh --reset
cd e2e && npx playwright test --project=bootstrap
```

Expected: PASS. Then run it again immediately — inside the same throttle minute — to prove the reuse path survived the edit:

```bash
npx playwright test --project=bootstrap
```

Expected: PASS. A 429 here means the extraction cost bootstrap its token reuse (ruling G7-R4) and must be fixed, not retried.

- [ ] **Step 5: Prove the rest of the suite is undisturbed**

```bash
cd e2e && npx playwright test --project=seeded
```

Expected: PASS (25 tests). This is the regression check on the file every project depends on.

- [ ] **Step 6: Commit**

Stage `e2e/setup/provision-admin.ts` and `e2e/setup/bootstrap.setup.ts` only, then commit with the message:

```
refactor(e2e): extract ensureSuperuser/provisionAdmin from bootstrap
```

---
### Task 3: The `instance` fixture

Implements the fixture table in **Piece B** of the spec. A test-scoped fixture wrapping `scripts/e2e_up.sh` through `execFile`, plus the `docker` reads the assertions need.

**Files:**
- Create: `e2e/fixtures/instance.ts`
- Modify: `e2e/fixtures/index.ts`

**Interfaces:**
- Consumes: `scripts/e2e_up.sh --recreate` from Task 1.
- Produces: the `instance` fixture, typed `Instance`, with methods `up`, `restart`, `recreate`, `down`, `pull`, `imageId`, `imageIdOf`, `startedAt`, `manage`. Exported from `e2e/fixtures/index.ts` alongside `test`.

**Ruling carried into this task:** the spec's method table omits a way to resolve the *local* image's id, which D11(d) needs in order to assert `.Image` equals it. `imageIdOf(ref)` is added for that. Cost if wrong: the upgrade spec would have to shell out itself, putting Docker calls back in a spec.

**Context the implementer needs:**

- The harness already assumes the process CWD is the Playwright rootDir (`e2e/`) — `e2e/setup/auth-files.ts` resolves `AUTH_DIR` as the bare relative path `playwright/.auth`, and `api.ts` and `principals.ts` do the same. Resolve the repo root the same way, and fail loudly if the script is not where that puts it.
- The container user is `dispatch`: `docker/entrypoint.sh` sets `POSTGRES_USER=${POSTGRES_USER:-dispatch}` and runs migrations as `su - "$POSTGRES_USER" -c "cd /app && python manage.py migrate --noinput"`. A **login** shell is required — the same file notes that `su -` strips env vars and that it propagates PATH through the login profile for exactly this reason.
- `execFile` has no default timeout and a 1 MB default `maxBuffer`. A cold boot can take 600s and `showmigrations --list` over 130 migrations is comfortably under 1 MB but the AIO build is not — set both explicitly.

- [ ] **Step 1: Create `e2e/fixtures/instance.ts`**

```ts
/**
 * Driving the Dispatcharr container's own lifecycle from inside a test.
 *
 * ---------------------------------------------------------------------------
 * WHO MAY IMPORT THIS
 * ---------------------------------------------------------------------------
 * Only the two lifecycle projects — `e2e/tests/lifecycle/`. Nothing else.
 *
 * Every other project in this suite shares one container for the length of a
 * run. This fixture stops, replaces and destroys that container, and
 * `scripts/e2e_up.sh`'s `destroy()` also removes the shared Docker network and
 * the `e2e-upstream` provider container along with it. A lifecycle spec
 * running beside `seeded` would therefore not merely disturb it — it would
 * delete the instance out from under it mid-assertion, and the failures would
 * surface in the *other* project, naming nothing.
 *
 * That is survivable only because the lifecycle projects run alone: their own
 * job and their own runner in CI (and, after D16, not even in the same
 * workflow as each other), plus a documented rule locally, alongside the same
 * rule that already applies to `pristine` and to `streaming-greybox`. See
 * `e2e/README.md`.
 *
 * ---------------------------------------------------------------------------
 * WHY IT SHELLS OUT
 * ---------------------------------------------------------------------------
 * `scripts/e2e_up.sh` is the single boot path — the same script a developer
 * runs and the same one `e2e-tests.yml` calls. Re-implementing `docker run`
 * with the right volume, network, port binding and readiness probe here would
 * be a second boot path that drifts from the first; that drift is exactly what
 * `e2e-tests.yml` stopped paying by calling the script instead of copying it.
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);

/**
 * Playwright runs with the config directory (`e2e/`) as CWD, which is the
 * assumption `setup/auth-files.ts`, `fixtures/api.ts` and `setup/principals.ts`
 * already encode by using bare relative paths. The repo root is its parent.
 */
const REPO_ROOT = path.resolve(process.cwd(), '..');
const SCRIPT = path.join(REPO_ROOT, 'scripts', 'e2e_up.sh');

/** Matches `scripts/e2e_up.sh`'s own default, and CI never overrides it. */
const CONTAINER =
  process.env.DISPATCHARR_E2E_CONTAINER ?? 'dispatcharr-e2e';

/**
 * `docker/entrypoint.sh`: `POSTGRES_USER=${POSTGRES_USER:-dispatch}`, and every
 * `manage.py` invocation in that file runs as `su - "$POSTGRES_USER"`. The
 * login dash is not cosmetic — the same file notes that `su -` strips the
 * environment and that it publishes PATH through the login profile precisely
 * so this form works.
 */
const APP_USER = 'dispatch';

/** A cold first boot on a CI runner has taken most of ten minutes. */
const SCRIPT_TIMEOUT_MS = 900_000;

/** `docker inspect` and `manage.py showmigrations` are fast and small. */
const DOCKER_TIMEOUT_MS = 120_000;

/** `docker pull` of a ~3.6 GB image. */
const PULL_TIMEOUT_MS = 900_000;

const MAX_BUFFER = 16 * 1024 * 1024;

export type UpOptions = {
  /** Sets `DISPATCHARR_E2E_IMAGE` for this invocation. */
  image?: string;
  /** Pass `--reset`: destroy the container *and* its volume first. */
  reset?: boolean;
};

export type ManageResult = {
  code: number;
  stdout: string;
  stderr: string;
};

type ExecError = Error & {
  code?: number | string;
  stdout?: string;
  stderr?: string;
};

function isExecError(error: unknown): error is ExecError {
  return error instanceof Error;
}

export class Instance {
  constructor() {
    if (!existsSync(SCRIPT)) {
      throw new Error(
        `scripts/e2e_up.sh not found at ${SCRIPT}. The instance fixture ` +
          'resolves the repo root as the parent of the process CWD, which ' +
          'assumes Playwright is running from `e2e/` — the same assumption ' +
          '`setup/auth-files.ts` makes. Run Playwright from `e2e/`.'
      );
    }
  }

  /**
   * Run `scripts/e2e_up.sh`, throwing an error that quotes its output.
   *
   * The script's own failure paths print container logs before exiting, so
   * carrying stdout into the message is the difference between "the boot
   * failed" and knowing why.
   */
  private async script(args: string[], env: NodeJS.ProcessEnv = {}): Promise<string> {
    try {
      const { stdout } = await run('bash', [SCRIPT, ...args], {
        cwd: REPO_ROOT,
        timeout: SCRIPT_TIMEOUT_MS,
        maxBuffer: MAX_BUFFER,
        env: {
          ...process.env,
          // The image is built once by CI and loaded from an artifact; letting
          // the script rebuild it would discard that and, since
          // e2e-upstream's ffmpeg is deliberately unpinned, is not guaranteed
          // to produce the same asset.
          DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD: '1',
          ...env,
        },
      });
      return stdout;
    } catch (error) {
      const details = isExecError(error)
        ? `${error.stdout ?? ''}${error.stderr ?? ''}`.trim() || error.message
        : String(error);
      throw new Error(
        `scripts/e2e_up.sh ${args.join(' ') || '(start)'} failed:\n${details}`
      );
    }
  }

  private async docker(args: string[], timeout = DOCKER_TIMEOUT_MS): Promise<string> {
    try {
      const { stdout } = await run('docker', args, {
        timeout,
        maxBuffer: MAX_BUFFER,
      });
      return stdout.trim();
    } catch (error) {
      const details = isExecError(error)
        ? `${error.stdout ?? ''}${error.stderr ?? ''}`.trim() || error.message
        : String(error);
      throw new Error(`docker ${args.join(' ')} failed:\n${details}`);
    }
  }

  /** Start the instance, reusing an existing container unless `reset` is set. */
  async up(options: UpOptions = {}): Promise<string> {
    return this.script(
      options.reset ? ['--reset'] : [],
      options.image ? { DISPATCHARR_E2E_IMAGE: options.image } : {}
    );
  }

  /**
   * Stop and start the *same* container — an in-place restart.
   *
   * Two invocations rather than `docker restart` so the second one goes
   * through the script's readiness probe: a restart that returns before
   * migrations and uWSGI are up would have every assertion after it racing
   * the boot.
   */
  async restart(): Promise<string> {
    await this.script(['--stop']);
    return this.script([]);
  }

  /** Replace the container, keep the volume — see `--recreate` in the script. */
  async recreate(options: { image: string }): Promise<string> {
    return this.script(['--recreate'], {
      DISPATCHARR_E2E_IMAGE: options.image,
    });
  }

  /** Destroy the container, its volume, the network and the provider. */
  async down(): Promise<string> {
    return this.script(['--down']);
  }

  /**
   * Pull `ref` and return its repo digest.
   *
   * Called before `up({ image: ref })` and never skipped: `e2e_up.sh` builds
   * from `docker/Dockerfile` when `docker image inspect` misses, so a
   * forgotten pull produces a "baseline" that is the local code under a
   * borrowed tag — a test comparing the image against itself, passing forever.
   */
  async pull(ref: string): Promise<string> {
    await this.docker(['pull', ref], PULL_TIMEOUT_MS);
    return this.docker([
      'image',
      'inspect',
      '-f',
      '{{index .RepoDigests 0}}',
      ref,
    ]);
  }

  /** The image id the running container was created from. */
  async imageId(): Promise<string> {
    return this.docker(['inspect', '-f', '{{.Image}}', CONTAINER]);
  }

  /** The image id a reference resolves to locally, for comparison with the above. */
  async imageIdOf(ref: string): Promise<string> {
    return this.docker(['image', 'inspect', '-f', '{{.Id}}', ref]);
  }

  /** The container's current start timestamp — proof a restart happened. */
  async startedAt(): Promise<string> {
    return this.docker(['inspect', '-f', '{{.State.StartedAt}}', CONTAINER]);
  }

  /**
   * Run `manage.py` inside the container, returning the exit code rather than
   * throwing — `migrate --check` exits non-zero *as its result*.
   *
   * `argv` is interpolated into a shell command, so it is restricted to plain
   * tokens. Nothing this suite needs is more than that, and accepting more
   * would make a fixture that shells into a container quietly able to run
   * anything.
   */
  async manage(argv: string[]): Promise<ManageResult> {
    for (const arg of argv) {
      if (!/^[A-Za-z0-9._/=-]+$/.test(arg)) {
        throw new Error(
          `instance.manage() argument ${JSON.stringify(arg)} contains ` +
            'characters that are not plain tokens. This runs through a shell ' +
            'inside the container; quote-free arguments only.'
        );
      }
    }
    const command = `cd /app && python manage.py ${argv.join(' ')}`;
    try {
      const { stdout, stderr } = await run(
        'docker',
        ['exec', CONTAINER, 'su', '-', APP_USER, '-c', command],
        { timeout: DOCKER_TIMEOUT_MS, maxBuffer: MAX_BUFFER }
      );
      return { code: 0, stdout, stderr };
    } catch (error) {
      if (isExecError(error) && typeof error.code === 'number') {
        return {
          code: error.code,
          stdout: error.stdout ?? '',
          stderr: error.stderr ?? '',
        };
      }
      throw new Error(
        `docker exec … manage.py ${argv.join(' ')} did not run: ${String(error)}`
      );
    }
  }
}
```

- [ ] **Step 2: Register the fixture in `e2e/fixtures/index.ts`**

Add the import beside the other fixture imports:

```ts
import { Instance } from './instance';
```

Add to the `Fixtures` type:

```ts
  instance: Instance;
```

Add to the `base.extend<Fixtures>({ … })` block:

```ts
  // Lifecycle projects only — `instance.ts`'s header says why, and it is not
  // a style preference: this fixture destroys the container every other
  // project is sharing. Lazy like every fixture here, so a spec that does not
  // name it never constructs one.
  instance: async ({}, use) => {
    await use(new Instance());
  },
```

Add to the exports at the bottom, beside `export { UpstreamClient, … }`:

```ts
export { Instance } from './instance';
export type { UpOptions, ManageResult } from './instance';
```

Then add a short entry to the `FIXTURES` section of the file's header comment, in the same style as the others:

```
 * `instance: Instance` — **lifecycle projects only.** Drives the container's
 * own lifecycle through `scripts/e2e_up.sh`: up/restart/recreate/down, plus
 * the `docker inspect` reads that prove the event happened and
 * `manage(argv)` for migration state. Destroys the container every other
 * project shares — read `./instance.ts`'s header before importing it.
```

- [ ] **Step 3: Typecheck**

```bash
cd e2e && npm run typecheck
```

Expected: clean.

- [ ] **Step 4: Prove the existing suite is undisturbed**

```bash
./scripts/e2e_up.sh --reset
cd e2e && npx playwright test --project=seeded
```

Expected: PASS. The fixture is lazy, so this proves adding it costs the other projects nothing.

- [ ] **Step 5: Commit**

Stage `e2e/fixtures/instance.ts` and `e2e/fixtures/index.ts` only, then commit with the message:

```
feat(e2e): add the instance fixture for container lifecycle control
```

---

### Task 4: Durable-state helper, the restart spec, and its CI wiring

Implements **D8**, **D11**, **D14** and inventory row 3. This task ships the first runnable lifecycle test.

**Files:**
- Create: `e2e/tests/lifecycle/durable-state.ts`
- Create: `e2e/tests/lifecycle/restart-persistence.spec.ts`
- Modify: `e2e/playwright.config.ts`
- Modify: `e2e/package.json`
- Modify: `.github/workflows/e2e-tests.yml`

**Interfaces:**
- Consumes: `provisionAdmin` (Task 2), the `instance` fixture (Task 3), `ApiClient`/`Seeder` from `e2e/fixtures`.
- Produces, from `./durable-state`:
  - `type DurableState`
  - `seedDurableState(api: ApiClient, seed: Seeder): Promise<DurableState>`
  - `assertDurableState(api: ApiClient, state: DurableState): Promise<void>`
  - `assertAdminTokenStillValid(request: APIRequestContext, access: string): Promise<void>`
  - `const MAX_SYSTEM_EVENTS: number`

**Context the implementer needs — do not rediscover these:**

- The seven-row set is **exactly what the `Seeder` factories already produce by default**, which is not a coincidence: `seed.streamProfile()` already sets `is_active: true` with a distinctive `parameters` string and cannot set `locked` (`StreamProfileOverrides` omits it deliberately, so a seeded profile is unlocked by construction); `seed.m3uAccount()` already defaults to inactive on `http://127.0.0.1:9/playlist.m3u`; `seed.epgSource()` likewise; `seed.user()` already defaults to `user_level: 1`. Only the `Channel`'s `channel_number` needs passing.
- `CoreSettings` mechanics, all three of which bite: the viewset has **no `lookup_field`**, so the row is addressed by **pk** — list `/api/core/settings/`, find the row whose `key` is `system_settings`, PATCH that id. `value` is the **whole group blob**, so the PATCH is read-modify-write or it silently drops `time_zone`, `preferred_region`, `auto_import_mapped_files`, `enable_ip_lookup` and `catchup_enabled`. And the assertion reads back **through the API**, never through `CoreSettings.get_system_settings`, which merges defaults on read (masking a clobbered blob) and reads through the Redis-backed cache, which is flushed on every boot.
- The `system_settings` row is guaranteed to exist: `core/migrations/0020_change_coresettings_value_to_jsonfield.py` creates it with `update_or_create`, carrying `time_zone` and `max_system_events`, and `0025` adds `preferred_region` and `auto_import_mapped_files`. A missing row is a real failure, not a case to paper over.
- Patching `system_settings` is inert by design: `CoreSettingsViewSet.update` special-cases only `STREAM_SETTINGS_KEY` (fires `rehash_streams.delay`) and `DVR_SETTINGS_KEY` (reschedules recordings), and `CoreSettingsSerializer.update` only `NETWORK_ACCESS_KEY` (CIDR validation). `max_system_events` only bounds `SystemEvent` retention.
- `listRows<T>(body)` from `e2e/setup/http.ts` handles both paginated and bare-array list responses. Use it.
- `whoAmI(request, access)` from `e2e/setup/login.ts` returns `Identity | null` and hits `/api/accounts/users/me/` — the one `UserViewSet` action that opts down to `Authenticated`. Use it for assertion (a) with the **raw pre-event access token**, not through `ApiClient`, whose refresh-on-401 would mask exactly the failure being tested.
- The lifecycle container has not been through `bootstrap`, so the `IntervalSchedule` row is not pre-warmed. That is safe here and only here: `workers: 1` with `fullyParallel: false` means the M3U account and the EPG source are created **serially**, so the `get_or_create` race that D10Scot/Dispatcharr#7 describes cannot occur.

- [ ] **Step 1: Create `e2e/tests/lifecycle/durable-state.ts`**

```ts
/**
 * The state both lifecycle specs create before their lifecycle event, and
 * assert afterwards.
 *
 * Postgres-backed rows only. Redis is excluded by construction rather than by
 * preference: AIO configures no persistence and `scripts/wait_for_redis.py`
 * calls `flushdb()` on every boot, so a Redis-backed persistence assertion
 * would be asserting a falsehood (spec D11).
 *
 * Every assertion is by id against a value recorded at creation. No counts, no
 * unfiltered lists — the roadmap's rule 4, and here it is also the only shape
 * that works: a re-run against a container that was not reset carries rows
 * from previous runs.
 */
import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import type { ApiClient, Seeder } from '../../fixtures';
import type {
  Channel,
  ChannelProfile,
  EpgSource,
  M3uAccount,
  StreamProfile,
  User,
} from '../../fixtures';
import { listRows } from '../../setup/http';
import { whoAmI } from '../../setup/login';
import { ADMIN } from '../../setup/credentials';

/**
 * Unmistakable, and nothing else in the suite uses it. The default is 100
 * (`CoreSettings.get_system_settings`), so a value read back as 100 after the
 * lifecycle event means the blob was lost and the defaults are being merged
 * back in — which is the failure this assertion exists to see.
 */
export const MAX_SYSTEM_EVENTS = 7317;

/** Nothing else exists on a fresh instance, so any number is free. */
const CHANNEL_NUMBER = 4242;

const SYSTEM_SETTINGS_KEY = 'system_settings';

type CoreSettingRow = {
  id: number;
  key: string;
  name: string;
  value: Record<string, unknown>;
};

export type DurableState = {
  channel: Channel;
  channelProfile: ChannelProfile;
  streamProfile: StreamProfile;
  m3uAccount: M3uAccount;
  epgSource: EpgSource;
  user: User;
  systemSettingsId: number;
};

async function systemSettingsRow(api: ApiClient): Promise<CoreSettingRow> {
  const res = await api.get('/api/core/settings/');
  const rows = listRows<CoreSettingRow>(
    await api.json(res, 'list core settings')
  );
  const row = rows.find((candidate) => candidate.key === SYSTEM_SETTINGS_KEY);
  expect(
    row,
    `no CoreSettings row with key "${SYSTEM_SETTINGS_KEY}". ` +
      'core/migrations/0020 creates it with update_or_create, so its absence ' +
      'is a real migration failure, not a fixture problem. Keys present: ' +
      rows.map((candidate) => candidate.key).join(', ')
  ).toBeDefined();
  return row!;
}

/**
 * Create the seven durable rows and return what a later assertion needs.
 *
 * Serial by construction — the lifecycle projects run one worker with
 * `fullyParallel: false` — which is what makes creating an M3U account and an
 * EPG source safe on a container `bootstrap` has never pre-warmed. Two
 * concurrent creates would both insert an `IntervalSchedule` row for the same
 * interval and brick the instance permanently (D10Scot/Dispatcharr#7).
 */
export async function seedDurableState(
  api: ApiClient,
  seed: Seeder
): Promise<DurableState> {
  const channel = await seed.channel({ channel_number: CHANNEL_NUMBER });
  const channelProfile = await seed.channelProfile();
  const streamProfile = await seed.streamProfile();
  const m3uAccount = await seed.m3uAccount();
  const epgSource = await seed.epgSource();
  const user = await seed.user();

  // Read-modify-write. `value` is the whole group blob, so spreading the
  // current one is not defensive style — a bare `{ max_system_events }`
  // silently drops time_zone, preferred_region, auto_import_mapped_files,
  // enable_ip_lookup and catchup_enabled.
  const row = await systemSettingsRow(api);
  const patched = await api.patch(`/api/core/settings/${row.id}/`, {
    value: { ...row.value, max_system_events: MAX_SYSTEM_EVENTS },
  });
  const written = await api.json<CoreSettingRow>(
    patched,
    'patch system_settings'
  );
  expect(
    written.value.max_system_events,
    'the PATCH response did not carry the new value back'
  ).toBe(MAX_SYSTEM_EVENTS);

  return {
    channel,
    channelProfile,
    streamProfile,
    m3uAccount,
    epgSource,
    user,
    systemSettingsId: row.id,
  };
}

/**
 * Assertion (a): a token minted *before* the lifecycle event still works.
 *
 * The cheapest specific proof that `/data` persisted. `DJANGO_SECRET_KEY` is
 * generated once into `/data/jwt` and reused on every subsequent boot
 * (`docker/entrypoint.sh`, `SECRET_FILE`); a regenerated key invalidates every
 * token in existence, so this fails loudly on a lost volume rather than
 * quietly re-authenticating.
 *
 * Deliberately not through `ApiClient`: it refreshes and retries once on a
 * 401, which would mask exactly this.
 */
export async function assertAdminTokenStillValid(
  request: APIRequestContext,
  access: string
): Promise<void> {
  const identity = await whoAmI(request, access);
  expect(
    identity?.username,
    'the access token minted before the lifecycle event no longer ' +
      'authenticates — /data/jwt did not survive, so DJANGO_SECRET_KEY was ' +
      'regenerated and every token in existence is now invalid'
  ).toBe(ADMIN.username);
}

/** Assertions (b) and (c): every row reads back by id, with its recorded values. */
export async function assertDurableState(
  api: ApiClient,
  state: DurableState
): Promise<void> {
  const channel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${state.channel.id}/`),
    'read back channel'
  );
  expect(channel.name).toBe(state.channel.name);
  expect(channel.channel_number).toBe(state.channel.channel_number);
  expect(channel.uuid).toBe(state.channel.uuid);

  const channelProfile = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${state.channelProfile.id}/`),
    'read back channel profile'
  );
  expect(channelProfile.name).toBe(state.channelProfile.name);

  const streamProfile = await api.json<StreamProfile>(
    await api.get(`/api/core/streamprofiles/${state.streamProfile.id}/`),
    'read back stream profile'
  );
  expect(streamProfile.name).toBe(state.streamProfile.name);
  expect(streamProfile.parameters).toBe(state.streamProfile.parameters);
  expect(streamProfile.is_active).toBe(state.streamProfile.is_active);
  expect(streamProfile.locked).toBe(state.streamProfile.locked);

  const m3uAccount = await api.json<M3uAccount>(
    await api.get(`/api/m3u/accounts/${state.m3uAccount.id}/`),
    'read back M3U account'
  );
  expect(m3uAccount.name).toBe(state.m3uAccount.name);
  expect(m3uAccount.server_url).toBe(state.m3uAccount.server_url);
  expect(m3uAccount.is_active).toBe(state.m3uAccount.is_active);

  const epgSource = await api.json<EpgSource>(
    await api.get(`/api/epg/sources/${state.epgSource.id}/`),
    'read back EPG source'
  );
  expect(epgSource.name).toBe(state.epgSource.name);
  expect(epgSource.url).toBe(state.epgSource.url);
  expect(epgSource.is_active).toBe(state.epgSource.is_active);

  const user = await api.json<User>(
    await api.get(`/api/accounts/users/${state.user.id}/`),
    'read back user'
  );
  expect(user.username).toBe(state.user.username);
  expect(user.user_level).toBe(state.user.user_level);

  // (c) — read through the API, never through `get_system_settings`, which
  // merges defaults on read and would report 7317's absence as the default 100
  // only if the blob were *missing a key*; a wholly lost row would come back
  // looking healthy.
  const settings = await api.json<CoreSettingRow>(
    await api.get(`/api/core/settings/${state.systemSettingsId}/`),
    'read back system_settings'
  );
  expect(
    settings.value.max_system_events,
    'max_system_events read back as the default — the settings blob did not ' +
      'survive the lifecycle event'
  ).toBe(MAX_SYSTEM_EVENTS);
}
```

- [ ] **Step 2: Create `e2e/tests/lifecycle/restart-persistence.spec.ts`**

```ts
/**
 * Exemplar: a spec that owns its container's lifecycle.
 *
 * COVERAGE: Lifecycle — restart preserves channels and settings (G7).
 *
 * Runs alone. `instance` destroys and replaces the container every other
 * project shares; see `e2e/fixtures/instance.ts`'s header.
 */
import { test, expect, ApiClient, Seeder } from '../../fixtures';
import { provisionAdmin } from '../../setup/provision-admin';
import {
  assertAdminTokenStillValid,
  assertDurableState,
  seedDurableState,
} from './durable-state';

test('durable state and the signing key survive a container restart', async ({
  instance,
  request,
  baseURL,
}, testInfo) => {
  await instance.up();

  // Not the `api`/`seed` fixtures: those read `playwright/.auth/`, written by
  // `bootstrap`, which this project does not depend on and must not — a
  // persisted pair describes an instance this spec is about to restart.
  const tokens = await provisionAdmin(request, baseURL!);
  const api = new ApiClient(request, tokens);
  const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId);
  const state = await seedDurableState(api, seed);

  const startedBefore = await instance.startedAt();
  await instance.restart();
  const startedAfter = await instance.startedAt();

  // (d) first, deliberately. Without it, a spec that silently failed to
  // restart anything passes every other assertion in this file — and passes
  // for as long as nobody reads it.
  expect(
    startedAfter,
    'the container never restarted: .State.StartedAt did not move'
  ).not.toBe(startedBefore);

  await assertAdminTokenStillValid(request, tokens.access);
  await assertDurableState(api, state);
});
```

- [ ] **Step 3: Add the `lifecycle` project to `e2e/playwright.config.ts`**

Append after the `streaming` project:

```ts
    {
      // Owns its container's lifecycle: restarts it mid-test. Must run alone —
      // `fixtures/instance.ts` has the reasoning, `e2e/README.md` has the rule.
      name: 'lifecycle',
      testDir: './tests/lifecycle',
      // The split between the two lifecycle projects is structural, not a
      // `--grep`: `--grep` matches test *titles*, so which spec ran would
      // depend on wording, and nothing would give this project the
      // complementary filter — it would run the ~9-minute upgrade spec too,
      // on every PR, which is exactly what D16 exists to prevent.
      testMatch: /restart-persistence\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      // Two container boots and a full readiness wait.
      timeout: 600_000,
      // Attempt 1 consumes the state attempt 2 would need — the same reason
      // `pristine` sets this, and here also because a retry would re-run
      // `provisionAdmin` against an instance that already has the superuser
      // and spend a login it does not need.
      retries: 0,
      // No `dependencies` and no `storageState`, for the same reason
      // `pristine` has neither: `bootstrap` targets whichever container is up
      // before a project starts, and this spec replaces the container
      // mid-run — a persisted token would point at an instance that no longer
      // exists.
    },
```

- [ ] **Step 4: Add the npm script and update the population message**

In `e2e/package.json`, replace the `test` script and add `test:lifecycle`:

```json
    "test": "echo 'Pick a population: npm run test:pristine | test:seeded | test:streaming | test:lifecycle — they need different container states and cannot share one invocation. test:lifecycle drives the container itself and must run alone.' && exit 1",
    "test:pristine": "playwright test --project=pristine",
    "test:seeded": "playwright test --project=seeded",
    "test:streaming": "playwright test --project=streaming",
    "test:lifecycle": "playwright test --project=lifecycle",
```

- [ ] **Step 5: Add `lifecycle` to the CI matrix**

In `.github/workflows/e2e-tests.yml`, the `test` job's matrix line becomes:

```yaml
        project: [pristine, seeded, streaming, lifecycle]
```

Nothing else in that file changes. The `changes` job's path pattern already covers `e2e/`, `docker/` and `scripts/`; the `e2e-result` gate depends on the `test` job as a whole, so a new matrix entry needs no edit there; and the job's existing `scripts/e2e_up.sh` boot step is left in place on purpose — it is idempotent, `instance.up()` short-circuits on the running container, and the container it produces has no superuser, which is what `provisionAdmin` needs.

- [ ] **Step 6: Typecheck**

```bash
cd e2e && npm run typecheck
```

Expected: clean.

- [ ] **Step 7: Run the spec**

```bash
./scripts/e2e_up.sh --reset
cd e2e && npm run test:lifecycle
```

Expected: 1 passed. If Docker is unavailable, say so in the report — do not describe this as verified.

- [ ] **Step 8: Verify the workflow edit passes zizmor**

The `PostToolUse` hook runs it automatically on the edit and blocks on any finding. If it did not fire, run it by hand and record the result.

- [ ] **Step 9: Commit**

Stage `e2e/tests/lifecycle/durable-state.ts`, `e2e/tests/lifecycle/restart-persistence.spec.ts`, `e2e/playwright.config.ts`, `e2e/package.json` and `.github/workflows/e2e-tests.yml` only, then commit with the message:

```
test(e2e): assert durable state survives a container restart
```

---
### Task 5: The upgrade spec

Implements **D10**, **D12**, **D16** and inventory row 4.

**Files:**
- Create: `e2e/tests/lifecycle/upgrade-migrations.spec.ts`
- Modify: `e2e/playwright.config.ts`
- Modify: `e2e/package.json`

**Interfaces:**
- Consumes: everything Task 4 produced, plus `instance.pull`, `instance.recreate`, `instance.imageId`, `instance.imageIdOf`, `instance.manage`, `instance.down` from Task 3.
- Produces: the `lifecycle-upgrade` Playwright project and the `test:lifecycle-upgrade` npm script, both consumed by Task 6's workflow.

**Ruling carried into this task (G7-R6):** the spec has Task 6's `build` job produce `dispatcharr-lifecycle:local` and the upgrade job `docker tag` it to `dispatcharr-e2e:local`. **Build it as `dispatcharr-e2e:local` directly instead** — the same tag `e2e-tests.yml` uses and `scripts/e2e_up.sh` defaults to — and let the two bash-suite jobs do the tagging into their own names. This deletes a step from the one job where the spec itself says a missing `docker tag` "fails as *the upgrade ran and the data survived* against the wrong image". The suite jobs still get exactly the tags they need. Cost if wrong: none identified.

**Context the implementer needs:**

- **D10's four fallback conditions**, all of which are normal paths rather than edge cases. `lifecycle-tests.yml` sets `DISPATCHARR_E2E_BASELINE_IMAGE` to `ghcr.io/d10scot/dispatcharr:<sha>`, where `<sha>` is `github.event.pull_request.base.sha` on a PR and `github.event.before` on a push. Neither field exists on `schedule` or `workflow_dispatch` — two of this workflow's four triggers — so the variable arrives **set but invalid**, as the literal `ghcr.io/d10scot/dispatcharr:`, not unset. All-zeroes is branch creation or a force-push. Registry non-resolution is independent of both: `docker-build.yml` publishes the SHA tag only when its own run succeeded.
- The `:latest` fallback is retained deliberately, and must **announce itself** — logged and attached — because `:latest` is written by *two* workflows on every push to main (`docker-build.yml` and `ci.yml`) and can therefore be the commit under test. A silent fallback is an upgrade test that upgrades from itself and passes vacuously.
- `GET /api/core/version/` **cannot** discriminate the baseline from the local build: `version.py` ships `__timestamp__ = None` and the Dockerfile only overwrites it when `TIMESTAMP` is passed, which `docker-build.yml` does not. Both may report `0.29.0` with a null timestamp. The swap is proved with `docker inspect`, never with the product.
- `docker/entrypoint.sh` runs `manage.py migrate --noinput` on **every** boot, before uWSGI starts, and `uwsgi started with PID` — which `scripts/e2e_up.sh`'s readiness probe transitively waits for — is printed after it. There is no separate migrate step to drive: readiness implies migrations completed.
- `showmigrations --list` prints an unindented app label followed by indented `[X] 0001_initial` lines. The applied set is `${app}.${name}` for the `[X]` rows.

- [ ] **Step 1: Verify `migrate --check`'s exit semantics against the pinned Django**

The spec requires this be checked at implementation time rather than assumed:

```bash
./scripts/e2e_up.sh
docker exec dispatcharr-e2e su - dispatch -c 'cd /app && python manage.py migrate --check' ; echo "exit=$?"
```

Expected on a fully-migrated instance: `exit=0`. Record the actual output in the report. If it is non-zero on a healthy instance, stop and report — the assertion in Step 2 would be inverted.

- [ ] **Step 2: Create `e2e/tests/lifecycle/upgrade-migrations.spec.ts`**

```ts
/**
 * COVERAGE: Lifecycle — upgrade from previous release (migrations) (G7).
 *
 * Start a published baseline image on a fresh volume, seed durable state, then
 * replace the container with the locally-built image on the *same* volume —
 * which is exactly what an upgrade is — and prove the migrations applied and
 * the data survived.
 *
 * Runs alone, in `lifecycle-tests.yml` rather than `e2e-tests.yml` (D16): at
 * ~9 minutes it does not fit the PR matrix, where the longest existing job is
 * 284s. The stated trade is that this spec is not self-guarding on PRs — its
 * own machinery (`docker/entrypoint.sh`, `scripts/e2e_up.sh`,
 * `e2e/fixtures/instance.ts`) is on that workflow's push filter but not its
 * pull_request one.
 *
 * On the fork having added zero migrations of its own: today this proves
 * little beyond "the container restarts onto its own data and Django's runner
 * does not choke on a no-op". It is scaffolding pointed at the right thing
 * from day one — it becomes meaningful the moment Phase 1 starts changing
 * models, and building it then is strictly harder than building it now.
 */
import { test, expect, ApiClient, Seeder } from '../../fixtures';
import type { Instance } from '../../fixtures';
import { provisionAdmin } from '../../setup/provision-admin';
import {
  assertAdminTokenStillValid,
  assertDurableState,
  seedDurableState,
} from './durable-state';

/** `scripts/e2e_up.sh`'s default `DISPATCHARR_E2E_IMAGE`, and the tag CI loads. */
const LOCAL_IMAGE = 'dispatcharr-e2e:local';

const FALLBACK_BASELINE = 'ghcr.io/d10scot/dispatcharr:latest';

/** `github.event.before` on a branch creation or a force-push. */
const ALL_ZEROES = /^0{40}$/;

type Baseline = { ref: string; reason: string };

/**
 * Resolve the baseline from the CI event, with D10's fallbacks.
 *
 * Three of the four conditions are decided here; the fourth — the tag not
 * resolving in the registry — can only be discovered by trying to pull it.
 */
function candidateBaseline(): Baseline {
  const configured = process.env.DISPATCHARR_E2E_BASELINE_IMAGE;
  if (!configured) {
    return {
      ref: FALLBACK_BASELINE,
      reason:
        'DISPATCHARR_E2E_BASELINE_IMAGE is unset — a local run, or a workflow ' +
        'that forgot to set it',
    };
  }

  const lastColon = configured.lastIndexOf(':');
  const lastSlash = configured.lastIndexOf('/');
  const tag = lastColon > lastSlash ? configured.slice(lastColon + 1) : null;

  if (tag === '') {
    return {
      ref: FALLBACK_BASELINE,
      reason:
        `${configured} has an empty tag — neither github.event.before nor ` +
        'github.event.pull_request.base.sha exists on a schedule or ' +
        'workflow_dispatch run, so the variable arrives set but invalid',
    };
  }
  if (tag !== null && ALL_ZEROES.test(tag)) {
    return {
      ref: FALLBACK_BASELINE,
      reason:
        `${configured} names the all-zeroes SHA — branch creation or a ` +
        'force-push, so there is no previous commit to upgrade from',
    };
  }
  return { ref: configured, reason: 'resolved from the CI event' };
}

/** The set of applied migrations, as `app.name`. */
async function appliedMigrations(instance: Instance): Promise<Set<string>> {
  const result = await instance.manage(['showmigrations', '--list']);
  expect(
    result.code,
    `showmigrations --list exited ${result.code}: ${result.stderr}`
  ).toBe(0);

  const applied = new Set<string>();
  let app = '';
  for (const line of result.stdout.split('\n')) {
    // An app label is the only unindented, single-token line in this output.
    const header = /^(\S+)\s*$/.exec(line);
    if (header) {
      app = header[1];
      continue;
    }
    const row = /^\s*\[([ X-])\]\s+(\S+)/.exec(line);
    if (row && row[1] === 'X') applied.add(`${app}.${row[2]}`);
  }

  expect(
    applied.size,
    `showmigrations --list reported no applied migrations:\n${result.stdout}`
  ).toBeGreaterThan(0);
  return applied;
}

test('an upgrade onto an existing volume applies migrations and keeps the data', async ({
  instance,
  request,
  baseURL,
}, testInfo) => {
  let baseline = candidateBaseline();
  let digest: string;
  try {
    digest = await instance.pull(baseline.ref);
  } catch (error) {
    if (baseline.ref === FALLBACK_BASELINE) throw error;
    baseline = {
      ref: FALLBACK_BASELINE,
      reason:
        `${baseline.ref} does not resolve in the registry — docker-build.yml ` +
        'publishes the SHA tag only when its own run succeeded ' +
        `(${String(error)})`,
    };
    digest = await instance.pull(baseline.ref);
  }

  // Announced, never silent. `:latest` is written by two workflows on every
  // push to main, so a fallback that nobody sees is an upgrade test that
  // upgraded from itself and passed.
  const provenance = `${baseline.ref}\n${digest}\n${baseline.reason}\n`;
  console.log(`Upgrade baseline: ${baseline.ref} (${digest}) — ${baseline.reason}`);
  await testInfo.attach('baseline-image.txt', {
    body: provenance,
    contentType: 'text/plain',
  });

  try {
    // reset: true — the baseline must boot onto a volume with no schema, or
    // it is not the older release creating the data this test carries forward.
    await instance.up({ image: baseline.ref, reset: true });

    const tokens = await provisionAdmin(request, baseURL!);
    const api = new ApiClient(request, tokens);
    const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId);

    const migrationsBefore = await appliedMigrations(instance);
    const state = await seedDurableState(api, seed);
    const baselineImageId = await instance.imageId();

    await instance.recreate({ image: LOCAL_IMAGE });

    // (d) first. Two independent guards on the same failure, deliberately:
    // `e2e_up.sh` reuses a container by name regardless of image, so a
    // `--recreate` that silently did nothing would leave the baseline running
    // and every assertion below would pass against it.
    const upgradedImageId = await instance.imageId();
    expect(
      upgradedImageId,
      'the container is still running the baseline image — the upgrade did ' +
        'not happen'
    ).not.toBe(baselineImageId);
    expect(
      upgradedImageId,
      `the container is not running ${LOCAL_IMAGE}`
    ).toBe(await instance.imageIdOf(LOCAL_IMAGE));

    // D12, first check: nothing is left unapplied. `docker/entrypoint.sh` runs
    // `migrate --noinput` on every boot before uWSGI starts, and the readiness
    // probe waits for uWSGI — so by here migrations have already run.
    const check = await instance.manage(['migrate', '--check']);
    expect(
      check.code,
      `migrate --check reported unapplied migrations:\n${check.stdout}\n${check.stderr}`
    ).toBe(0);

    // D12, second check — the one `--check` cannot make. A migration renamed,
    // deleted or squashed out from under existing data leaves nothing
    // unapplied and is exactly the failure this row exists for.
    const migrationsAfter = await appliedMigrations(instance);
    const vanished = [...migrationsBefore].filter(
      (migration) => !migrationsAfter.has(migration)
    );
    expect(
      vanished,
      'migrations that were applied on the baseline are no longer applied ' +
        'after the upgrade — one was renamed, deleted or squashed out from ' +
        'under existing data'
    ).toEqual([]);

    await assertAdminTokenStillValid(request, tokens.access);
    await assertDurableState(api, state);
  } finally {
    // `--down` also removes the shared network and the provider container,
    // which is survivable exactly because this project runs alone.
    await instance.down();
  }
});
```

- [ ] **Step 3: Add the `lifecycle-upgrade` project to `e2e/playwright.config.ts`**

Append after the `lifecycle` project:

```ts
    {
      // Identical settings to `lifecycle` — the split is which spec runs, not
      // how. Separate projects rather than one project plus `--grep` because
      // `--grep` matches test *titles*: which spec ran would depend on wording
      // nobody has written yet, and `lifecycle` would have no complementary
      // filter, so it would run this ~9-minute spec on every PR (D16).
      name: 'lifecycle-upgrade',
      testDir: './tests/lifecycle',
      testMatch: /upgrade-migrations\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      // A ~3.6 GB baseline pull, a fresh boot on an empty volume, a container
      // replacement and a second boot.
      timeout: 600_000,
      retries: 0,
    },
```

- [ ] **Step 4: Add the npm script**

In `e2e/package.json`, after `test:lifecycle`:

```json
    "test:lifecycle-upgrade": "playwright test --project=lifecycle-upgrade",
```

and extend the `test` script's message to list it:

```json
    "test": "echo 'Pick a population: npm run test:pristine | test:seeded | test:streaming | test:lifecycle | test:lifecycle-upgrade — they need different container states and cannot share one invocation. The two lifecycle populations drive the container themselves and must run alone.' && exit 1",
```

- [ ] **Step 5: Typecheck**

```bash
cd e2e && npm run typecheck
```

Expected: clean.

- [ ] **Step 6: Run the spec**

```bash
cd e2e && npm run test:lifecycle-upgrade
```

Expected: 1 passed, with a `Upgrade baseline: …` line naming `ghcr.io/d10scot/dispatcharr:latest` and the reason `DISPATCHARR_E2E_BASELINE_IMAGE is unset`. This is the local path and it exercises the fallback deliberately.

Then prove the event-resolved path works too, using a SHA `docker-build.yml` has actually published:

```bash
cd e2e && DISPATCHARR_E2E_BASELINE_IMAGE=ghcr.io/d10scot/dispatcharr:d22d3378a0b4b8ba97d1b4e5d1cd05cbd2c93cbe npm run test:lifecycle-upgrade
```

If that tag no longer resolves, find one that does with
`gh api /users/d10scot/packages/container/dispatcharr/versions --jq '.[].metadata.container.tags[]' | head -20`
and say in the report which you used. A pull failure here should take the registry fallback and still pass — that is condition four, and seeing it fire is the point.

Then prove the empty-tag path:

```bash
cd e2e && DISPATCHARR_E2E_BASELINE_IMAGE=ghcr.io/d10scot/dispatcharr: npm run test:lifecycle-upgrade
```

Expected: passes, announcing `has an empty tag`.

If Docker or the network is unavailable for any of these, say which ran and which did not — do not describe unrun steps as verified.

- [ ] **Step 7: Commit**

Stage `e2e/tests/lifecycle/upgrade-migrations.spec.ts`, `e2e/playwright.config.ts` and `e2e/package.json` only, then commit with the message:

```
test(e2e): assert an upgrade applies migrations and keeps the data
```

---

### Task 6: `lifecycle-tests.yml`

Implements **Piece A** — **D3**, **D4**, **D5**, **D6**, **D7** and D16's `upgrade-migrations` job.

**Files:**
- Create: `.github/workflows/lifecycle-tests.yml`

**Interfaces:**
- Consumes: `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` **unmodified**; the `lifecycle-upgrade` project from Task 5.
- Produces: nothing other tasks consume.

**Context the implementer needs:**

- **Expect the zizmor hook to block.** It fires on `Write|Edit` to any `.github/workflows/*.yml`, blocks on *every* finding in the file, and the workflows are at zero findings — a ratchet, not a warning. The same check runs in CI as `actions-lint.yml` against the same pinned version. A workflow-level `permissions:` elevation, a floating tag, a checkout without `persist-credentials: false`, or a `${{ }}` interpolated straight into a `run:` block will each stop the edit landing.
- **`pipefail` is non-negotiable and already the default.** GitHub's default `bash` shell sets `-eo pipefail`, so `run: … | tee …` reports the suite's status correctly — *unless* somebody adds a custom `shell:`. Without it the job goes **green on failure**. Say so in a comment at the step.
- **`--keep-on-fail` is not passed.** Global constraint 2.
- The suites take a single positional scenario name for local reproduction. Put that command in the job summary.

- [ ] **Step 1: Create `.github/workflows/lifecycle-tests.yml`**

```yaml
name: Lifecycle Tests

# Deliberately path-filtered, unlike its sibling e2e-tests.yml.
#
# e2e-tests.yml always triggers on pull requests because the Main ruleset
# requires its checks, and a path-filtered workflow leaves a required check
# "Expected" forever — blocking the merge permanently. Nothing here is a
# required check, and nothing here should become one: this workflow builds the
# AIO image and pulls four more, so making it unconditional would put roughly
# an hour on every pull request. If a check from this file is ever added to the
# ruleset, the filters below must come off in the same change.
on:
  push:
    branches: [main]
    paths:
      - 'docker/**'
      - '**/migrations/**'
      - 'scripts/e2e_up.sh'
      - 'scripts/wait_for_redis.py'
      - 'dispatcharr/settings.py'
      - 'e2e/tests/lifecycle/**'
      # The lifecycle projects depend on the shared fixtures, on the config,
      # and on `provisionAdmin` in e2e/setup — a change to any of them can
      # break these specs while touching nothing else the filter would see.
      - 'e2e/fixtures/**'
      - 'e2e/setup/**'
      - 'e2e/playwright.config.ts'
      - '.github/workflows/lifecycle-tests.yml'
  # Narrow on purpose (D16): only the upgrade job runs here, gating the class
  # of change it exists to catch. `**/models.py` is not padding — a model
  # change is what *necessitates* a migration, and a PR that alters one without
  # shipping the migration is exactly the case filtering on migrations alone
  # would miss.
  pull_request:
    branches: [main]
    paths:
      - '**/migrations/**'
      - '**/models.py'
  # Earns its place: these suites pull postgres:16, postgres:17, redis:latest
  # and upstream's :latest — four floating tags whose contents change under
  # this repository, and which no path filter can ever notice.
  schedule:
    - cron: '17 4 * * 1'
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: lifecycle-tests-${{ github.workflow }}-${{ github.ref }}
  # Conditional because this workflow is two things. Cancelling a post-merge
  # run drops lifecycle signal for every commit but the last in a run of
  # merges, and those commits are already on main. On a pull request the
  # ordinary latency argument applies: without this, three pushes to a
  # migration-touching PR queue three serialised runs, each carrying a
  # 45-minute-budget AIO build.
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  # Deliberately NOT gated off on pull requests. The upgrade job needs it, and
  # a skipped dependency skips the dependent — which would make every PR run a
  # silent no-op that reports green.
  build:
    name: Build AIO image
    runs-on: ubuntu-latest
    # A wedged docker build otherwise burns the 6-hour default.
    timeout-minutes: 45
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      # Tagged exactly as e2e-tests.yml tags it, and as scripts/e2e_up.sh
      # defaults to, so the upgrade job needs no retagging step. One build for
      # every consumer: docker/Dockerfile:14 uses `npm install` with no
      # lockfile, so N builds can produce N different frontend bundles.
      - name: Build the image
        run: docker build -f docker/Dockerfile -t dispatcharr-e2e:local .

      # Neither lifecycle spec uses the provider, but scripts/e2e_up.sh starts
      # it unconditionally and waits for /scenarios before starting
      # Dispatcharr, and the instance fixture sets
      # DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD — so without this image in the
      # artifact the script dies at a `docker image inspect` of a tag nothing
      # built. It is a hard startup dependency of the boot path, not a test
      # dependency, which is exactly why it is easy to omit.
      - name: Build the upstream provider image
        run: docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream

      - name: Export both images
        run: docker save dispatcharr-e2e:local dispatcharr-e2e-upstream:local | gzip > /tmp/dispatcharr-lifecycle.tar.gz

      - name: Upload the image
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: dispatcharr-lifecycle-image
          path: /tmp/dispatcharr-lifecycle.tar.gz
          retention-days: 1

  # Two parallel jobs rather than one sequential one: serial would put 20-30
  # minutes on the critical path after an already-long build, and parallel
  # halves peak disk — each job pulls its own subset onto a runner with
  # single-digit gigabytes free after a 3.6 GB image load, and the puid suite
  # creates a PostgreSQL data volume per scenario. `fail-fast: false` so one
  # red suite names itself while the other still reports.
  #
  # Skipped on pull requests: the pull_request trigger exists for the upgrade
  # job alone (D16), and these two pull four-plus images and take 10-15 minutes
  # each.
  suites:
    name: ${{ matrix.name }}
    runs-on: ubuntu-latest
    needs: build
    if: github.event_name != 'pull_request'
    # The suites document 10-15 minutes. The headroom is for the two
    # pg_upgrade scenarios, which `apt install` a PostgreSQL major version
    # inside the container at runtime and raise their own readiness budget to
    # 300s each.
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: puid-pgid
            script: docker/tests/test-puid-pgid.sh
            tag: puid-test
          - name: tls-postgres
            script: docker/tests/test-tls-postgres.sh
            tag: tls-test
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Download the image
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with:
          name: dispatcharr-lifecycle-image
          path: /tmp

      - name: Load the image
        run: docker load < /tmp/dispatcharr-lifecycle.tar.gz

      # The tag adapts to the script, not the other way round: both suites
      # hard-code their own IMAGE_NAME and take --skip-build, so one shared
      # build reaches both without either suite being edited.
      - name: Tag the image as the suite expects
        env:
          SUITE_TAG: ${{ matrix.tag }}
        run: docker tag dispatcharr-e2e:local "dispatcharr:${SUITE_TAG}"

      # Two things are load-bearing here and neither is obvious.
      #
      # `pipefail`: GitHub's default `bash` shell sets `-eo pipefail`, so the
      # suite's exit status survives the pipe into tee. Add a custom `shell:`
      # to this step and the job goes GREEN ON FAILURE.
      #
      # No `--keep-on-fail`: it looks like the obvious diagnosability answer
      # and makes things strictly worse. All eight TLS scenarios reuse the same
      # container names, so keeping one failure's containers makes the next
      # `docker run --name` collide — turning one real failure into six
      # fabricated ones. The puid suite's keep-branch tests a run-global error
      # counter, so after the first failure it stops cleaning up everything,
      # accumulating up to 20 containers and PostgreSQL data volumes on a
      # runner with single-digit gigabytes free.
      - name: Run the suite
        env:
          SUITE_SCRIPT: ${{ matrix.script }}
          SUITE_LOG: ${{ runner.temp }}/${{ matrix.name }}.log
        run: bash "${SUITE_SCRIPT}" --skip-build 2>&1 | tee "${SUITE_LOG}"

      # Every assertion in both suites is `docker logs | grep`, `docker exec
      # stat` or `docker exec psql`, so a bare red X carries no information.
      # The suites clean up on failure by default, so this finds whatever is
      # still standing rather than everything — the tee'd log above is the
      # durable record.
      - name: Container state (on failure)
        if: failure()
        run: |
          docker ps -a
          for container in $(docker ps -aq); do
            echo "=== ${container} ==="
            docker logs "${container}" 2>&1 | tail -n 100 || true
          done

      - name: Name the one-scenario re-run command
        if: failure()
        env:
          SUITE_SCRIPT: ${{ matrix.script }}
        run: |
          {
            echo "### ${SUITE_SCRIPT} failed"
            echo
            echo "Reproduce one scenario locally — both suites take a single positional scenario name:"
            echo
            echo '```'
            echo "bash ${SUITE_SCRIPT} --skip-build <scenario_name>"
            echo '```'
            echo
            echo "Do **not** add \`--keep-on-fail\`. The TLS suite reuses one set of container names across all eight scenarios, so keeping one failure's containers cascades into six fabricated ones; the puid suite's keep-branch is run-global and accumulates containers and PostgreSQL volumes."
          } >> "${GITHUB_STEP_SUMMARY}"

      - name: Upload the suite log
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: lifecycle-suite-log-${{ matrix.name }}
          path: ${{ runner.temp }}/${{ matrix.name }}.log
          retention-days: 7
          if-no-files-found: warn

  # The one job in this workflow that runs Playwright (D16). It lives here
  # rather than in e2e-tests.yml's matrix because ~9 minutes on every PR would
  # roughly double E2E latency, where the longest existing job is 284s — and it
  # is free here, because `build` above already produced the image.
  upgrade-migrations:
    name: upgrade-migrations
    runs-on: ubuntu-latest
    needs: build
    # Matches the suite jobs: this one loads the 3.6 GB artifact and then pulls
    # a baseline of comparable size.
    timeout-minutes: 45
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Download the image
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with:
          name: dispatcharr-lifecycle-image
          path: /tmp

      # Restores both dispatcharr-e2e:local and dispatcharr-e2e-upstream:local
      # — the tags scripts/e2e_up.sh defaults to, so nothing needs retagging.
      - name: Load the image
        run: docker load < /tmp/dispatcharr-lifecycle.tar.gz

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

      # Every e2e job in e2e-tests.yml is gated on this, and a project that
      # does not typecheck cannot be trusted to have driven Docker correctly.
      - name: Typecheck
        working-directory: ./e2e
        run: npm run typecheck

      # The baseline is resolved from the CI event, never `:latest`: two
      # workflows push `:latest` on every push to main, so `:latest` can be the
      # commit under test and the upgrade would upgrade from itself, passing
      # vacuously while looking perfectly green. Both fields below name a
      # commit that is on main, is an ancestor of the code under test, and is
      # never that code — and docker-build.yml publishes a full-40-char SHA tag
      # for every push to main.
      #
      # Neither field exists on a schedule or workflow_dispatch run, so the
      # variable is set-but-invalid there rather than unset. The spec handles
      # that, along with the all-zeroes SHA of a branch creation or force-push,
      # and a tag that does not resolve in the registry — announcing which
      # fallback it took and attaching the resolved digest either way.
      - name: Run the upgrade spec
        working-directory: ./e2e
        env:
          E2E_BASE_URL: http://localhost:9191
          DISPATCHARR_E2E_BASELINE_IMAGE: ghcr.io/d10scot/dispatcharr:${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event.before }}
        run: npx playwright test --project=lifecycle-upgrade

      - name: Container logs (on failure)
        if: failure()
        run: |
          docker ps -a
          docker logs dispatcharr-e2e 2>&1 | tail -n 200 || true
          docker logs e2e-upstream 2>&1 | tail -n 100 || true

      # playwright.config.ts sets trace: 'retain-on-failure' and screenshot:
      # 'only-on-failure', so these exist on a failure and would otherwise be
      # discarded with the runner. The tee'd logs above cover the bash suites
      # and nothing else covers this job.
      - name: Upload Playwright report
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        with:
          name: playwright-report-lifecycle-upgrade
          path: e2e/playwright-report/
          retention-days: 7
          if-no-files-found: ignore

      - name: Stop the container
        if: always()
        run: docker rm -f dispatcharr-e2e || true
```

- [ ] **Step 2: Confirm zizmor is clean**

The `PostToolUse` hook runs on the Write and blocks on any finding. If it did not fire, run the same check by hand and record the output. Expected: no findings.

- [ ] **Step 3: Lint the YAML with actionlint**

`actions-lint.yml` runs `actionlint` in CI, so a syntax or expression error here is a red check.

```bash
actionlint .github/workflows/lifecycle-tests.yml
```

Expected: no output. If `actionlint` is not installed locally, say so and rely on the CI job.

- [ ] **Step 4: Verify the matrix scripts exist and take the flags used**

```bash
ls -l docker/tests/test-puid-pgid.sh docker/tests/test-tls-postgres.sh
git diff --stat HEAD -- docker/tests/
```

Expected: both files present; the diff is **empty**. Global constraint 1 — the suites are not modified. A non-empty diff here fails the task.

- [ ] **Step 5: Optionally run one bash scenario locally**

The suites have never executed anywhere. Running one cheap scenario now is worth more than the first CI run being a complete unknown:

```bash
docker tag dispatcharr-e2e:local dispatcharr:puid-test
bash docker/tests/test-puid-pgid.sh --skip-build fresh_default
```

Record the outcome verbatim in the report — pass or fail. **A failure here is data, not a blocker**: it is the expected outcome of a first run, and per the spec it gets triaged into "suite bug" (a follow-up PR that says so) or "product bug" (an issue, global constraint 3) — never a pre-emptive edit to a suite nobody has watched fail. If it fails, file the issue and note it; do not fix the suite.

- [ ] **Step 6: Commit**

Stage `.github/workflows/lifecycle-tests.yml` only, then commit with the message:

```
ci(e2e): run the PUID/PGID and TLS Postgres suites, and the upgrade spec
```

---

### Task 7: Documentation

Roadmap rule 3 and **D14**. The inventory is how seven agents avoid duplicating each other and avoid leaving silent gaps.

**Files:**
- Modify: `e2e/COVERAGE.md`
- Modify: `e2e/README.md`

**Interfaces:** consumes everything above; produces nothing.

- [ ] **Step 1: Move the four G7 rows to `done` in `e2e/COVERAGE.md`**

The four rows currently read:

```
| Lifecycle | Upgrade from previous release (migrations) | G7 | todo |
| Lifecycle | Restart preserves channels and settings | G7 | todo |
| Lifecycle | PUID/PGID honoured | G7 | todo |
| Lifecycle | TLS Postgres connection | G7 | todo |
```

Change each `todo` to `done`. Match whatever column format the surrounding `done` rows use — if they name the covering artifact, name these ones too:

- Upgrade from previous release (migrations) → `e2e/tests/lifecycle/upgrade-migrations.spec.ts`
- Restart preserves channels and settings → `e2e/tests/lifecycle/restart-persistence.spec.ts`
- PUID/PGID honoured → `docker/tests/test-puid-pgid.sh`, run by `.github/workflows/lifecycle-tests.yml`
- TLS Postgres connection → `docker/tests/test-tls-postgres.sh`, run by `.github/workflows/lifecycle-tests.yml`

**Read the surrounding rows before editing** — do not invent a column shape.

- [ ] **Step 2: Add the two projects to `e2e/README.md`'s Projects table**

After the `streaming` row (and after whatever rows G4 has added, if it landed first):

```
| `lifecycle` | Restarts the container mid-test. **Runs alone** — it destroys the container every other project shares. No `bootstrap` dependency: it provisions its own admin |
| `lifecycle-upgrade` | Boots a published baseline image, seeds, then replaces the container with the local build on the same volume. **Runs alone.** Runs in `lifecycle-tests.yml`, not in `e2e-tests.yml`'s matrix |
```

- [ ] **Step 3: Extend the "runs alone" paragraph**

`e2e/README.md` already carries a paragraph naming the projects that cannot share a container with `pristine`. Add the two lifecycle projects to it, with the specific reason: they do not merely need a different container state, they **destroy** the container, its volume, the shared network and the `e2e-upstream` provider. Point at `e2e/fixtures/instance.ts`'s header.

Add the local invocations:

```bash
./scripts/e2e_up.sh --reset && npm run test:lifecycle
npm run test:lifecycle-upgrade   # pulls a ~3.6 GB baseline; brings its own instance up and down
```

- [ ] **Step 4: Update the CI section**

The README's CI section describes the matrix as a hardcoded three-job list and obliges a new project to be added to it. Update it to say:

- the matrix is now four jobs — `pristine`, `seeded`, `streaming`, `lifecycle` (plus whatever G4 added);
- `lifecycle-upgrade` is the one project **deliberately not** in that matrix: it runs in `.github/workflows/lifecycle-tests.yml`, because ~9 minutes on every PR would roughly double E2E latency where the longest existing job is 284s;
- `lifecycle-tests.yml` also runs the two bash suites, `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh`, which had no workflow before;
- that workflow is **path-filtered and must not be made a required check** — a required check that never reports blocks the merge forever, which is exactly why `e2e-tests.yml` has no `pull_request` paths filter.

Keep the existing obligation sentence ("nothing wires new projects in automatically") — it is still true and is why this section needs maintaining.

- [ ] **Step 5: Verify no other README claim went stale**

```bash
grep -n 'three-job\|three projects\|pristine, seeded and streaming' e2e/README.md
```

Fix anything that now undercounts.

- [ ] **Step 6: Commit**

Stage `e2e/COVERAGE.md` and `e2e/README.md` only, then commit with the message:

```
docs(e2e): record the four G7 lifecycle rows as covered
```

---

## Self-review

**Spec coverage.** Every decision maps to a task: D1 → the Task 1-5 / Task 6 split; D2 → global constraint 1, enforced by Task 6 Step 4's empty-diff check; D3, D5, D6, D7 → Task 6; D4 → Task 6 Step 1's trigger block; D8 → Task 4 Step 3 and Task 5 Step 3; D9 → Task 1; D10 → Task 5 Step 2's `candidateBaseline` and Task 6's `DISPATCHARR_E2E_BASELINE_IMAGE`; D11 → Task 4's `durable-state.ts` and both specs' (d) assertions; D12 → Task 5 Steps 1-2; D13 → Task 2 (as amended by G7-R4); D14 → Task 4 Steps 4-5 and Task 5 Step 4; D15 → global constraint 3, with Task 6 Step 5 as the place it is most likely to fire; D16 → Task 5's project split and Task 6's `upgrade-migrations` job. Inventory rows 1-4 → Tasks 6, 6, 4, 5. Non-goals are respected: no Dockerfile is edited, the bash suites are not modified, `CLAUDE.md` is not touched.

**Type consistency.** `provisionAdmin` returns `TokenPair`, which `ApiClient`'s constructor accepts as its optional second argument — verified against `e2e/fixtures/api.ts`. `Seeder`'s constructor is `(api, workerIndex, testId)`, matching both specs' `new Seeder(api, testInfo.workerIndex, testInfo.testId)`. `instance.manage` returns `ManageResult` with a numeric `code`, which is what `migrate --check` and `showmigrations` are read through. `DurableState` is produced by `seedDurableState` and consumed by `assertDurableState` in both specs.

**Two things deliberately left to the implementer's judgment**, because the plan cannot see the file at edit time: `e2e/COVERAGE.md`'s exact column shape, and where in `e2e/README.md`'s "runs alone" paragraph the new sentence belongs. Both are Task 7 and both say "read the surrounding rows first".
