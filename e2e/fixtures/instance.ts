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

/** Ditto — the tag `scripts/e2e_up.sh` builds or expects for the fake provider. */
const UPSTREAM_IMAGE =
  process.env.DISPATCHARR_E2E_UPSTREAM_IMAGE ?? 'dispatcharr-e2e-upstream:local';

/**
 * Readiness budget for every boot this fixture drives.
 *
 * `scripts/e2e_up.sh` defaults to 60 polls at 5s = 300s. `e2e-tests.yml` raises
 * its own boot step to 120 and says why: the default "suits a laptop with a warm
 * volume rather than a cold runner". Every boot here is at least as cold —
 * `up({ reset: true })` destroys the volume, so the upgrade spec pays `initdb`,
 * 130 migrations and `collectstatic` on a CI runner, the same work `pristine`
 * does with twice this budget.
 *
 * Set here rather than per-workflow-job so no future caller has to remember, and
 * deferring to an explicit override so a workflow can still raise it further.
 */
const READY_ATTEMPTS = process.env.DISPATCHARR_E2E_READY_ATTEMPTS ?? '120';

/**
 * `docker/entrypoint.sh`: `POSTGRES_USER=${POSTGRES_USER:-dispatch}`, and every
 * `manage.py` invocation in that file runs as `su - "$POSTGRES_USER"`. The
 * login dash is not cosmetic — the same file notes that `su -` strips the
 * environment and that it publishes PATH through the login profile precisely
 * so this form works.
 */
const APP_USER = 'dispatch';

/**
 * These three must stay *below* the calling project's Playwright timeout, or
 * they are unreachable and the generic "Test timeout of Ns exceeded" wins.
 *
 * That matters more than it sounds. `scripts/e2e_up.sh` prints the container's
 * logs before giving up, and this fixture quotes that output into its error —
 * so whichever of the two timeouts fires first decides whether a failed boot
 * arrives with a traceback or with nothing at all. See the timeouts on the two
 * lifecycle projects in `playwright.config.ts`, which are sized against these.
 */

/**
 * The script's own budget dominates this: its readiness loop is
 * `DISPATCHARR_E2E_READY_ATTEMPTS` (120) × 5s = 600s, plus a 30s provider wait.
 * 720s leaves the script room to fail on its own terms — with logs — rather
 * than being killed mid-poll.
 */
const SCRIPT_TIMEOUT_MS = 720_000;

/** `docker inspect` and `manage.py showmigrations` are fast and small. */
const DOCKER_TIMEOUT_MS = 120_000;

/** `docker pull` of a ~3.6 GB image; minutes on a cold runner, not tens of them. */
const PULL_TIMEOUT_MS = 600_000;

const MAX_BUFFER = 16 * 1024 * 1024;

export type UpOptions = {
  /**
   * Sets `DISPATCHARR_E2E_IMAGE` for this invocation.
   *
   * **Only meaningful together with `reset: true`.** `scripts/e2e_up.sh` reuses
   * an existing container by *name* and never compares its image id, so
   * `up({ image })` against a container that is already there keeps serving the
   * old one. Passing `image` without `reset` throws rather than quietly doing
   * nothing — use {@link Instance.recreate} to swap the image while keeping the
   * volume.
   */
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
   * True once this test has created or replaced the container, so teardown
   * knows whether the instance is ours to destroy.
   *
   * `up()` without `reset` *adopts* whatever is already running — that is how
   * the restart spec works, and how a developer's container survives
   * `npm run test:lifecycle`. Only `up({ reset: true })` and `recreate()` take
   * ownership.
   */
  owned = false;

  /**
   * Whether to tell the script to skip building the fake upstream provider.
   *
   * Only when the image is already here. In CI it always is — `build` saves it
   * into the artifact alongside the AIO image and the job `docker load`s both —
   * and skipping matters there, because rebuilding would discard the artifact
   * every other consumer is testing, and `e2e-upstream`'s ffmpeg is deliberately
   * unpinned so a second build is not guaranteed to carry the same asset.
   *
   * Setting it unconditionally was wrong locally and failed late and
   * confusingly: `scripts/e2e_up.sh` skips the build and then reads the image id
   * anyway under `set -e`, so a fresh clone died at `No such image` — after
   * `test:lifecycle-upgrade` had already spent ten minutes pulling a 3.6 GB
   * baseline, having just printed that it was "using the loaded artifact".
   *
   * Only a genuinely absent image answers "build it". A daemon hiccup or a
   * timeout here would otherwise rebuild `e2e-upstream` from source in CI,
   * silently replacing the loaded artifact — the exact drift this flag exists
   * to prevent — so anything else is rethrown.
   */
  private async skipUpstreamBuild(): Promise<boolean> {
    try {
      await this.docker(['image', 'inspect', '-f', '{{.Id}}', UPSTREAM_IMAGE]);
      return true;
    } catch (error) {
      if (/no such image|No such object/i.test(String(error))) return false;
      throw new Error(
        `could not determine whether ${UPSTREAM_IMAGE} exists, so refusing to ` +
          'guess whether to rebuild it (rebuilding in CI would discard the ' +
          `loaded artifact): ${String(error)}`
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
    const skipUpstream = await this.skipUpstreamBuild();
    try {
      const { stdout } = await run('bash', [SCRIPT, ...args], {
        cwd: REPO_ROOT,
        timeout: SCRIPT_TIMEOUT_MS,
        maxBuffer: MAX_BUFFER,
        env: {
          ...process.env,
          DISPATCHARR_E2E_READY_ATTEMPTS: READY_ATTEMPTS,
          ...(skipUpstream
            ? { DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD: '1' }
            : {}),
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
    if (options.image && !options.reset) {
      throw new Error(
        'up({ image }) without `reset: true` does nothing: scripts/e2e_up.sh ' +
          'reuses an existing container by name and never compares its image ' +
          'id, so it would keep serving the old image while this call looked ' +
          'like it had switched. Use `up({ image, reset: true })` to start ' +
          'fresh on that image, or `recreate({ image })` to swap it while ' +
          'keeping the volume.'
      );
    }
    if (options.reset) this.owned = true;
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
    this.owned = true;
    return this.script(['--recreate'], {
      DISPATCHARR_E2E_IMAGE: options.image,
    });
  }

  /**
   * The container's recent log output, for attaching to a failed test.
   *
   * Read this *before* `down()`. The workflow's `failure()` step runs
   * `docker logs` too, but by then teardown has removed the container, so it
   * printed "No such container" behind a `|| true` — every upgrade failure
   * arrived with no container logs, for a test whose failures are usually
   * inside the container.
   */
  async logs(tail = 300): Promise<string> {
    // Not via `docker()`, which returns stdout only: a container's stderr is
    // where the interesting half lives (the entrypoint's tracebacks, Django's
    // migration errors), and `docker logs` keeps the two streams separate.
    const { stdout, stderr } = await run(
      'docker',
      ['logs', '--tail', String(tail), CONTAINER],
      { timeout: DOCKER_TIMEOUT_MS, maxBuffer: MAX_BUFFER }
    );
    return `${stdout}${stderr}`;
  }

  /** Destroy the container, its volume, the network and the provider. */
  async down(): Promise<string> {
    const output = await this.script(['--down']);
    this.owned = false;
    return output;
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
