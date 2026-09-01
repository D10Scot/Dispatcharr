/**
 * Every grey-box escape hatch in the suite, and exactly who may use it.
 *
 * `quarantine.spec.ts` established the principle for one of these — "a
 * convention plus a README decays silently. This does not." — and policed the
 * string `greybox/redis` only. `node:child_process` was already imported by a
 * second spec and would have been accepted silently in any new one.
 *
 * These capabilities are the ones that break when the relay moves out of the
 * Django workers, so keeping their use to a short, deliberate list is what
 * makes the rest of the suite portable. Adding a file here is a reviewable
 * decision; adding one by accident is not possible.
 *
 * NOT an import-graph check, and this is worth recording so it is not
 * re-attempted: `e2e/fixtures/index.ts` imports and re-exports `./instance`,
 * which imports `node:child_process`, and `e2e/README.md`'s "Writing a test"
 * makes importing `../../fixtures` mandatory. Every test therefore
 * *transitively* reaches subprocess execution, and a reachability guard flags
 * all 77 spec files. Use is the only thing worth policing.
 *
 * Scope is `tests/`, `fixtures/` and `setup/`. The goal definition said
 * `tests/**` alone; scanning only that would move the hole rather than close
 * it, since a grey-box helper added under `fixtures/` and imported from a test
 * would be invisible.
 */
export type Capability = {
  /** Appears in the failure message. */
  name: string;
  /** Why it is grey-box — the sentence a reviewer needs to judge an addition. */
  why: string;
  /** Every file permitted to use it, relative to `e2e/`. Sorted on comparison. */
  allow: readonly string[];
};

export const CONTAINER_LIFECYCLE: Capability = {
  name: 'the `instance` fixture (container lifecycle)',
  why: 'Restarts, replaces and upgrades the container — the subject of the lifecycle projects, and meaningless once the relay is a separate process.',
  allow: [
    // The two lifecycle specs are the container's lifecycle, by definition.
    // `fixtures/instance.ts` owns the fixture and `fixtures/index.ts` wires it
    // in; neither destructures it, so neither appears here.
    'tests/lifecycle/restart-persistence.spec.ts',
    'tests/lifecycle/upgrade-migrations.spec.ts',
  ],
};

export const SUBPROCESS: Capability = {
  name: 'a direct `node:child_process` import',
  why: 'Runs commands against the container host. Nothing a client can observe.',
  allow: [
    // Owns container lifecycle: `docker run`, `docker rm`, e2e_up.sh.
    'fixtures/instance.ts',
    // The grey-box Redis helper shells into the container's redis-cli.
    'fixtures/greybox/redis.ts',
    // Counts `ffmpeg` processes with `pgrep -x` to prove Output Profile
    // sharing — a container-wide observable with no client-facing equivalent.
    'tests/streaming-greybox/output-profile-sharing.spec.ts',
  ],
};

export const GREYBOX_REDIS: Capability = {
  name: 'the grey-box Redis helper',
  why: 'Reads Redis key shapes directly. The keys are internal and the extraction is expected to change them.',
  allow: [
    // The one spec the original quarantine.spec.ts allowlisted.
    'tests/streaming-greybox/output-profile-sharing.spec.ts',
  ],
};

export const CONTAINER_INTROSPECTION: Capability = {
  name: 'a container-introspection command in a string literal (`pgrep`, `docker `, `manage.py`)',
  why: 'Observes process tables, container state or Django internals rather than a client-facing surface.',
  allow: [
    // Builds the `docker` and `manage.py` command lines the container is
    // driven with.
    'fixtures/instance.ts',
    // `pgrep -x ffmpeg`, to count transcodes container-wide.
    'tests/streaming-greybox/output-profile-sharing.spec.ts',
  ],
};

/**
 * Eight files match `grep -rln "pgrep\|manage\.py\|docker "`. Exactly two —
 * the two listed above — use a marker in code. **The other six match only in
 * comments** and are deliberately absent:
 *
 * - `fixtures/greybox/redis.ts` — documents its `docker exec … redis-cli`
 *   command lines in a header comment; assembles the real ones from argument
 *   arrays.
 * - `tests/lifecycle/upgrade-migrations.spec.ts` — drives the container
 *   through the `instance` fixture and only *discusses* docker and
 *   `manage.py`. Its capability is `CONTAINER_LIFECYCLE`, above.
 * - `fixtures/index.ts`, `fixtures/seed.ts`, `tests/seeded/output-m3u.spec.ts`,
 *   `tests/frontend/plugins.spec.ts` — all prose.
 *
 * Six of eight is why `capabilities.spec.ts` parses instead of scanning text.
 * A guard that fires on prose gets loosened until it catches nothing, and the
 * loosening would have to be three-quarters of the rule.
 */

/**
 * Writes to `/api/core/settings/` — every one of which is instance-wide.
 *
 * See `capabilities.spec.ts`'s sibling, `global-mutation.spec.ts`, for why the
 * rule is the endpoint rather than a list of keys, and why serialising a
 * project does not substitute for this list.
 */
export const GLOBAL_SETTINGS_WRITE: Capability = {
  name: 'a write to /api/core/settings/ (instance-wide)',
  why: 'Every CoreSettings row is a settings group affecting the whole instance, and two of them are read through caches that outlive the test that wrote them.',
  allow: [
    // Reads every group and PATCHes `system_settings` to prove durable state
    // survives a restart and an upgrade. Runs in the `lifecycle` projects,
    // which own the container and share it with nothing.
    'tests/lifecycle/durable-state.ts',
    // Raises `proxy_settings.buffering_speed` for its run. `streaming-failover`
    // is `workers: 1` for exactly this reason.
    'tests/streaming-failover/failover-buffering.spec.ts',
    // Sets the catch-up stream profile to Redirect for its run.
    'tests/streaming-failover/catchup-redirect.spec.ts',
    // Sets `stream_settings.default_stream_profile` to Redirect for its run.
    // `streaming-greybox` is `workers: 1` partly for this reason.
    'tests/streaming-greybox/vod-redirect-profile.spec.ts',
  ],
};
