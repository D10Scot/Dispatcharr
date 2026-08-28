// Probe (2026-08-28, run against the live `dispatcharr-e2e` container):
//
//   $ docker exec dispatcharr-e2e redis-cli CONFIG GET protected-mode
//   protected-mode
//   yes
//   $ docker exec dispatcharr-e2e redis-cli CONFIG GET requirepass
//   requirepass
//   (empty)
//   $ docker run --rm --network dispatcharr-e2e-net redis:7-alpine \
//       redis-cli -h dispatcharr-e2e -p 6379 PING
//   DENIED Redis is running in protected mode because protected mode is
//   enabled and no password is set for the default user. In this mode
//   connections are only accepted from the loopback interface.
//
// `CONFIG GET bind` reports `* -::*`, which looks permissive and is not:
// protected mode only stands down when the bind was set *explicitly*, and
// that value is the built-in default of a bare `redis-server` started with
// no config file. Reading the config alone cannot settle whether a
// non-loopback client can connect — only a real connection attempt can, and
// it answered DENIED. So the published-port branch is dead; this file talks
// to Redis exclusively through `docker exec ... redis-cli --json`, which
// runs loopback-side of protected mode because it executes *inside* the
// container. `scripts/e2e_up.sh` is not modified by this file or anything
// that depends on it.
//
// One correction versus the task brief: the brief names the override
// variable `DISPATCHARR_E2E_NAME`, but `scripts/e2e_up.sh` actually reads
// `DISPATCHARR_E2E_CONTAINER` (defaulting to `dispatcharr-e2e`) — there is
// no `DISPATCHARR_E2E_NAME` anywhere in the repo. This file follows the
// script, not the brief, so a non-default container name actually works.

/**
 * The ONLY sanctioned way an E2E test reaches Redis.
 *
 * This file is quarantined on purpose. Phase 3 of this fork's stated
 * direction removes Redis from the video data path entirely, at which point
 * every test importing this helper must be rewritten or deleted. Keeping the
 * coupling in one file, imported only from `e2e/tests/streaming-greybox/`,
 * makes that blast radius a single grep instead of an archaeology exercise.
 *
 * The allowlist below is enforced by `quarantine.spec.ts`, not by convention.
 * If you are adding an import from outside that directory, you are doing
 * something the extraction will have to undo. Reconsider.
 */
export const GREYBOX_ALLOWLIST = [
  'tests/streaming-greybox/output-profile-sharing.spec.ts',
  'tests/streaming-greybox/ownership-lease.spec.ts',
];

export interface GreyboxRedis {
  get(key: string): Promise<string | null>;
  del(key: string): Promise<number>;
  keys(pattern: string): Promise<string[]>;
}

import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

// Matches scripts/e2e_up.sh's own NAME default exactly, so a caller who
// overrode the container name when bringing the stack up doesn't need to
// override it again here.
const CONTAINER_NAME = process.env.DISPATCHARR_E2E_CONTAINER || 'dispatcharr-e2e';

/**
 * Runs `redis-cli --json <args>` inside the `dispatcharr-e2e` container and
 * parses the result. `--json` is what makes this safe: GET/DEL/KEYS all come
 * back as valid JSON (`null`, a quoted string, an integer, or an array of
 * strings) with no ad hoc string parsing on this end.
 */
async function redisCli<T>(...args: string[]): Promise<T> {
  const { stdout } = await execFileAsync('docker', [
    'exec',
    CONTAINER_NAME,
    'redis-cli',
    '--json',
    ...args,
  ]);
  return JSON.parse(stdout.trim()) as T;
}

export function greyboxRedis(): GreyboxRedis {
  return {
    get: (key) => redisCli<string | null>('GET', key),
    del: (key) => redisCli<number>('DEL', key),
    keys: (pattern) => redisCli<string[]>('KEYS', pattern),
  };
}
