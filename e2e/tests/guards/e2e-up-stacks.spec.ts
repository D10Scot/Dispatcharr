/**
 * `scripts/e2e_up.sh` tears down only what is its own, and refuses a
 * half-scoped invocation before touching Docker at all.
 *
 * Two tracker issues, one mechanism. **#168**: the fake provider is shared
 * by default (`UPSTREAM_NAME` is `e2e-upstream` whatever the stack's own
 * scoping variables say), but `--down`/`--reset` removed it and `--stop`
 * stopped it whichever stack asked — and a provider recreated because its
 * image moved came back attached to only the invoking stack's network,
 * silently dropping every sibling stack's container-name DNS to it. **#187**:
 * every scoping variable defaults independently, so setting
 * `DISPATCHARR_E2E_CONTAINER` alone (say) yields a private app container on
 * the shared network, the shared volume and the shared provider — and a
 * Playwright-side upstream URL that names a different provider than the one
 * the script will actually start is a guaranteed-broken run whose symptom
 * ("stream ended after 188 bytes") names nothing.
 *
 * `@characterization`: this pins the local harness script's own container
 * choreography — which network a shared provider keeps, which invocation
 * refuses outright, what the provider is told about its own name. No client
 * observes any of it, and a rewrite of the harness (a different tool
 * entirely, say) is free to choose a different shape. `docs/adr/0002` is the
 * authority for the tag.
 *
 * Every test drives the REAL `scripts/e2e_up.sh` with `spawnSync`, against a
 * stub `docker`/`curl` on `PATH` (`e2e-up-stub.sh`, this directory) — never
 * a mock of the script's own functions. **Safety precheck**, run before
 * every invocation: `command -v docker` under the test's own `PATH` must
 * resolve to the stub wrapper, or the test throws before the script runs —
 * so a broken `PATH` can never reach a real Docker daemon, and the #187
 * refusal cases (which by design never even reach a `docker` call) are
 * doubly protected by a precheck that ran first. Every scoping variable in
 * every test carries a random `h1g-` prefix for the same reason.
 *
 * `tests/guards/` is exempt from the capability scan (`capabilities.spec.ts`,
 * `allowlist.ts`): this spec runs no container and touches no real Docker
 * daemon, and the precheck above is what proves it.
 *
 * The real-Docker claims this stub encodes (the range-template output shape,
 * a stopped container still listing its network attachments, a missing
 * object's exit 1) are cross-checked against actual Docker 29.8 by the PR's
 * Task 1.4, on throwaway `h1r-`-prefixed containers — not by this spec,
 * which never runs a real container.
 */
import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { REPO_ROOT } from './ast';

const STUB_PATH = path.join(__dirname, 'e2e-up-stub.sh');
const SCRIPT_PATH = path.join(REPO_ROOT, 'scripts', 'e2e_up.sh');

type Mode = '' | '--stop' | '--down' | '--reset' | '--recreate';
const ALL_MODES: Mode[] = ['', '--stop', '--down', '--reset', '--recreate'];

/** One shared bin dir for the whole file: the wrapper scripts carry no
 * per-test state, only the stub's argv, so there is nothing to gain from
 * recreating them per test. */
let TMP_BIN: string;

test.beforeAll(() => {
  TMP_BIN = fs.mkdtempSync(path.join(os.tmpdir(), 'h1g-bin-'));
  fs.writeFileSync(
    path.join(TMP_BIN, 'docker'),
    `#!/bin/sh\nexec bash "${STUB_PATH}" "$@"\n`,
    { mode: 0o755 },
  );
  fs.writeFileSync(
    path.join(TMP_BIN, 'curl'),
    `#!/bin/sh\nexec env STUB_AS=curl bash "${STUB_PATH}" "$@"\n`,
    { mode: 0o755 },
  );
});

test.afterAll(() => {
  fs.rmSync(TMP_BIN, { recursive: true, force: true });
  for (const dir of createdStates) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

function scopedPath(): string {
  return `${TMP_BIN}:${process.env.PATH ?? ''}`;
}

/**
 * `process.env` with every `DISPATCHARR_E2E_*`/`E2E_UPSTREAM_*` key removed.
 *
 * Without this, a shell already exporting the plan's Global constraint 6
 * overrides — exactly the environment every H-2..H-5 implementer works in —
 * leaked into every test here: the script saw a stack or provider it was
 * never told about by the test itself, not the one the test seeded. Verified
 * by mutation: with those exports set in the shell, 25 of 27 tests failed
 * before this function existed; reverting to a plain `...process.env` spread
 * reproduces that failure.
 */
function cleanBaseEnv(): NodeJS.ProcessEnv {
  const base: NodeJS.ProcessEnv = {};
  const leaks = /^(DISPATCHARR_E2E_|E2E_UPSTREAM_)/;
  for (const [k, v] of Object.entries(process.env)) {
    if (leaks.test(k)) continue;
    base[k] = v;
  }
  return base;
}

/**
 * The safety precheck the header promises: proves `docker` on `PATH`
 * resolves to the stub wrapper, in the exact environment about to be used.
 * Runs at the top of every `runScript()` call rather than as a bare
 * `test.beforeEach`, because it must see the same `PATH` the script itself
 * is about to run under, and that is assembled per invocation, not once per
 * test.
 */
function assertPathIsStubbed(env: NodeJS.ProcessEnv): void {
  const check = spawnSync('bash', ['-c', 'command -v docker'], { env, encoding: 'utf8' });
  const resolved = (check.stdout ?? '').trim();
  const expected = path.join(TMP_BIN, 'docker');
  if (resolved !== expected) {
    throw new Error(
      `Safety precheck failed: PATH resolves docker to '${resolved || '(nothing)'}', ` +
        `not the stub wrapper '${expected}'. Refusing to run scripts/e2e_up.sh — see this ` +
        `file's header for why.`,
    );
  }
}

function randomSuffix(): string {
  return randomBytes(4).toString('hex');
}

/** A throwaway, fully-scoped stack's names. Every test gets its own. */
function mkStack() {
  const r = randomSuffix();
  return {
    container: `h1g-${r}-app`,
    volume: `h1g-${r}-vol`,
    network: `h1g-${r}-net`,
    port: '39191',
    upstream: `h1g-${r}-up`,
    upstreamPort: '39402',
  };
}

/** Every state dir created this run, so `afterAll` can remove them. */
const createdStates: string[] = [];

function createState(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'h1g-state-'));
  createdStates.push(dir);
  return dir;
}

function seedNetwork(state: string, name: string): void {
  fs.mkdirSync(path.join(state, 'n'), { recursive: true });
  fs.writeFileSync(path.join(state, 'n', name), '');
}

function seedContainer(
  state: string,
  name: string,
  opts: { image?: string; running?: boolean; networks?: string[] } = {},
): void {
  const dir = path.join(state, 'c', name);
  fs.mkdirSync(dir, { recursive: true });
  if (opts.image !== undefined) fs.writeFileSync(path.join(dir, 'image'), `${opts.image}\n`);
  if (opts.running ?? true) fs.writeFileSync(path.join(dir, 'running'), '');
  if (opts.networks) {
    fs.writeFileSync(path.join(dir, 'networks'), `${opts.networks.join('\n')}\n`);
  }
}

function readLog(state: string): string[] {
  const p = path.join(state, 'log');
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.length > 0);
}

function containerNetworks(state: string, name: string): string[] {
  const p = path.join(state, 'c', name, 'networks');
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.length > 0);
}

function containerExists(state: string, name: string): boolean {
  return fs.existsSync(path.join(state, 'c', name));
}

function networkExists(state: string, name: string): boolean {
  return fs.existsSync(path.join(state, 'n', name));
}

function containerRunning(state: string, name: string): boolean {
  return fs.existsSync(path.join(state, 'c', name, 'running'));
}

function containerEnvLines(state: string, name: string): string[] {
  const p = path.join(state, 'c', name, 'env');
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.length > 0);
}

type RunResult = { status: number | null; stdout: string; stderr: string; log: string[] };

/**
 * Runs the real script under `bash` (or `bashPath`, for the bash-3.2
 * variant), with the stub on `PATH` and a fresh, caller-owned state dir.
 * Never a mode of `undefined` by omission-by-accident: `mode === ''` sends
 * no positional argument at all, which is what an empty string in the
 * plan's mode list means (`"${1:-}"` treats a missing $1 and an empty $1
 * identically).
 */
function runScript(
  mode: Mode,
  env: NodeJS.ProcessEnv,
  state: string,
  bashPath = 'bash',
): RunResult {
  const fullEnv: NodeJS.ProcessEnv = {
    ...cleanBaseEnv(),
    ...env,
    STUB_STATE: state,
    PATH: scopedPath(),
  };
  assertPathIsStubbed(fullEnv);
  const args = [SCRIPT_PATH, ...(mode ? [mode] : [])];
  const result = spawnSync(bashPath, args, { env: fullEnv, encoding: 'utf8' });
  return {
    status: result.status,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
    log: readLog(state),
  };
}

/** Every test's closing invariant: the stub recognised every call the
 * script made. An `UNHANDLED` line means either the script does something
 * this stub does not model, or (the mutation Task 1.5 exists to prove) the
 * fix reverted to a shape the stub was deliberately built not to answer. */
function expectNoUnhandled(log: string[]): void {
  expect(log.filter((l) => l.startsWith('UNHANDLED'))).toEqual([]);
}

test.describe('e2e_up.sh: stack teardown scoping', () => {
  test(
    '--down of a second stack leaves a provider another stack is attached to running (#168)',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();
      seedNetwork(state, 'h1g-other-net');
      seedNetwork(state, stack.network);
      seedContainer(state, stack.upstream, {
        image: 'sha256:whatever',
        running: true,
        networks: ['h1g-other-net', stack.network],
      });

      const result = runScript('--down', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
      }, state);

      expect(result.status).toBe(0);
      expect(containerExists(state, stack.upstream)).toBe(true);
      expect(containerNetworks(state, stack.upstream)).toEqual(['h1g-other-net']);
      expect(result.log.some((l) => l === `docker rm -f ${stack.upstream}`)).toBe(false);
      expect(networkExists(state, stack.network)).toBe(false);
      expectNoUnhandled(result.log);
    },
  );

  test(
    '--down of the only stack on a provider still removes it',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();
      seedNetwork(state, stack.network);
      seedContainer(state, stack.upstream, {
        image: 'sha256:whatever',
        running: true,
        networks: [stack.network],
      });

      const result = runScript('--down', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
      }, state);

      expect(result.status).toBe(0);
      expect(containerExists(state, stack.upstream)).toBe(false);
      expectNoUnhandled(result.log);
    },
  );

  test(
    "--stop of a second stack leaves a shared provider running (#187's incident)",
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();
      seedNetwork(state, 'h1g-other-net');
      seedNetwork(state, stack.network);
      seedContainer(state, stack.upstream, {
        image: 'sha256:whatever',
        running: true,
        networks: ['h1g-other-net', stack.network],
      });

      const result = runScript('--stop', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
      }, state);

      expect(result.status).toBe(0);
      expect(containerRunning(state, stack.upstream)).toBe(true);
      expect(result.log.some((l) => l === `docker stop ${stack.upstream}`)).toBe(false);
      expectNoUnhandled(result.log);
    },
  );

  test(
    '--stop of the only stack on a provider still stops it',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();
      seedNetwork(state, stack.network);
      seedContainer(state, stack.upstream, {
        image: 'sha256:whatever',
        running: true,
        networks: [stack.network],
      });

      const result = runScript('--stop', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
      }, state);

      expect(result.status).toBe(0);
      expect(containerRunning(state, stack.upstream)).toBe(false);
      expect(result.log.some((l) => l === `docker stop ${stack.upstream}`)).toBe(true);
      expectNoUnhandled(result.log);
    },
  );

  test(
    'a provider recreated because its image moved is reattached to every stack it served (#168)',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();
      seedNetwork(state, 'h1g-other-net');
      seedNetwork(state, stack.network);
      // The app image already exists, so the flow skips straight to the
      // provider: only the provider's own image id is under test here.
      fs.mkdirSync(path.join(state, 'i'), { recursive: true });
      fs.writeFileSync(path.join(state, 'i', `${stack.container}-img:local`), 'sha256:appimg\n');
      seedContainer(state, stack.upstream, {
        image: 'sha256:old',
        running: true,
        networks: ['h1g-other-net', stack.network],
      });

      const result = runScript('', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_IMAGE: `${stack.container}-img:local`,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
        STUB_NEXT_IMAGE_ID: 'sha256:new',
      }, state);

      expect(result.status).toBe(0);
      expect(new Set(containerNetworks(state, stack.upstream))).toEqual(
        new Set(['h1g-other-net', stack.network]),
      );
      expect(result.stdout).toMatch(/lose every scenario they had created/);
      expectNoUnhandled(result.log);
    },
  );

  test(
    'a renamed provider is told its own name as its internal origin (#168 comment)',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();

      const result = runScript('', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_IMAGE: `${stack.container}-img:local`,
        DISPATCHARR_E2E_UPSTREAM_CONTAINER: stack.upstream,
        DISPATCHARR_E2E_UPSTREAM_PORT: stack.upstreamPort,
      }, state);

      expect(result.status).toBe(0);
      const runLine = result.log.find(
        (l) => l.startsWith('docker run') && l.includes(`--name ${stack.upstream} `),
      );
      expect(runLine).toBeDefined();
      expect(runLine).toContain(`-e UPSTREAM_INTERNAL_ORIGIN=http://${stack.upstream}:8080`);
      expect(containerEnvLines(state, stack.upstream)).toContain(
        `UPSTREAM_INTERNAL_ORIGIN=http://${stack.upstream}:8080`,
      );
      expectNoUnhandled(result.log);
    },
  );
});

test.describe('e2e_up.sh: check_scope (#187)', () => {
  const STACK_VARS = [
    'DISPATCHARR_E2E_CONTAINER',
    'DISPATCHARR_E2E_VOLUME',
    'DISPATCHARR_E2E_NETWORK',
  ] as const;

  for (const soleVar of STACK_VARS) {
    for (const mode of ALL_MODES) {
      test(
        `a partially scoped invocation (${soleVar} alone, mode '${mode || '(none)'}') refuses before touching docker (#187)`,
        { tag: '@characterization' },
        () => {
          const state = createState();
          const env: NodeJS.ProcessEnv = { [soleVar]: `h1g-${randomSuffix()}` };

          const result = runScript(mode, env, state);

          expect(result.status).toBe(2);
          expect(result.stderr).toContain('Refusing a partially scoped stack');
          for (const v of STACK_VARS) {
            if (v !== soleVar) expect(result.stderr).toContain(v);
          }
          expect(result.log).toEqual([]);
        },
      );
    }
  }

  // The reverse direction of the loop above (#187 in the other direction,
  // found in review round 1): a private provider set with no scoped stack
  // at all used to pass check_scope, leaving --down/--reset free to act on
  // the *shared* app container, its volume and its network.
  for (const mode of ALL_MODES) {
    test(
      `a private provider with no scoped stack refuses before touching docker, mode '${mode || '(none)'}' (#187)`,
      { tag: '@characterization' },
      () => {
        const state = createState();
        const env: NodeJS.ProcessEnv = {
          DISPATCHARR_E2E_UPSTREAM_CONTAINER: `h1g-${randomSuffix()}-up`,
          DISPATCHARR_E2E_UPSTREAM_PORT: '39402',
        };

        const result = runScript(mode, env, state);

        expect(result.status).toBe(2);
        expect(result.stderr).toContain(
          'a private provider needs a scoped stack: set DISPATCHARR_E2E_CONTAINER, _VOLUME, _NETWORK and _PORT',
        );
        expect(result.log).toEqual([]);
      },
    );
  }

  test(
    'an upstream override without its port refuses (#187)',
    { tag: '@characterization' },
    () => {
      const state = createState();
      const result = runScript('', { DISPATCHARR_E2E_UPSTREAM_CONTAINER: `h1g-${randomSuffix()}` }, state);

      expect(result.status).toBe(2);
      expect(result.stderr).toContain('DISPATCHARR_E2E_UPSTREAM_CONTAINER and _UPSTREAM_PORT go together');
      expect(result.log).toEqual([]);
    },
  );

  test(
    'the converse: an upstream port override without its container refuses (#187)',
    { tag: '@characterization' },
    () => {
      const state = createState();
      const result = runScript('', { DISPATCHARR_E2E_UPSTREAM_PORT: '39402' }, state);

      expect(result.status).toBe(2);
      expect(result.stderr).toContain('DISPATCHARR_E2E_UPSTREAM_CONTAINER and _UPSTREAM_PORT go together');
      expect(result.log).toEqual([]);
    },
  );

  test(
    'a Playwright upstream URL that names another provider refuses (#187)',
    { tag: '@characterization' },
    () => {
      const state = createState();
      const result = runScript('', {
        E2E_UPSTREAM_INTERNAL_URL: 'http://e2e-upstream-pr6:8080',
      }, state);

      expect(result.status).toBe(2);
      expect(result.stderr).toContain('e2e-upstream-pr6');
      expect(result.stderr).toContain('e2e-upstream');
      expect(result.log).toEqual([]);
    },
  );

  test(
    'a Playwright upstream control URL naming the wrong port refuses (#187)',
    { tag: '@characterization' },
    () => {
      const state = createState();
      const result = runScript('', {
        E2E_UPSTREAM_CONTROL_URL: 'http://127.0.0.1:19999',
      }, state);

      expect(result.status).toBe(2);
      expect(result.stderr).toContain('19999');
      expect(result.stderr).toContain('9402');
      expect(result.log).toEqual([]);
    },
  );

  test(
    'a fully scoped stack with the shared provider is accepted',
    { tag: '@characterization' },
    () => {
      const stack = mkStack();
      const state = createState();

      const result = runScript('', {
        DISPATCHARR_E2E_CONTAINER: stack.container,
        DISPATCHARR_E2E_VOLUME: stack.volume,
        DISPATCHARR_E2E_NETWORK: stack.network,
        DISPATCHARR_E2E_PORT: stack.port,
        DISPATCHARR_E2E_IMAGE: `${stack.container}-img:local`,
        DISPATCHARR_E2E_UPSTREAM_IMAGE: `${stack.container}-up-img:local`,
      }, state);

      expect(result.status).toBe(0);
      expect(result.stderr).not.toContain('Refusing a partially scoped stack');
      expectNoUnhandled(result.log);
    },
  );

  test(
    'a partially scoped invocation still refuses under bash 3.2, not just bash >= 4.4',
    { tag: '@characterization' },
    () => {
      const probe = spawnSync('/bin/bash', ['-c', 'echo "${BASH_VERSINFO[0]}"'], {
        encoding: 'utf8',
      });
      const major = parseInt((probe.stdout ?? '').trim(), 10);
      test.skip(
        !(probe.status === 0 && major < 4),
        '/bin/bash is not a pre-4.4 bash here (CI\'s ubuntu runner ships bash 5); ' +
          "the string-based check_scope build (no arrays, per the #187 analysis) is " +
          'untestable at this host and relies on the macOS development-machine run instead.',
      );

      const state = createState();
      const result = runScript(
        '',
        { DISPATCHARR_E2E_CONTAINER: `h1g-${randomSuffix()}` },
        state,
        '/bin/bash',
      );

      expect(result.status).toBe(2);
      expect(result.stderr).toContain('Refusing a partially scoped stack');
      expect(result.log).toEqual([]);
    },
  );
});
