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
    // An app label is the only unindented, single-token line in this output —
    // and that is load-bearing, not merely descriptive. `manage.py` prints six
    // banner lines to *stdout* before any command output ("Redis TLS:
    // disabled", "Setting log level to: INFO", …), so this parser always sees
    // a preamble. It survives only because every one of those lines contains a
    // space. A future banner line that is a single bare word would be read as
    // an app label here and every migration after it misattributed to it.
    // `\S+` rather than `[a-z_]+`: `m3u` is a real app label.
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
