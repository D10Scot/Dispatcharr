/**
 * A backup taken, the database mutated, the backup restored.
 *
 * COVERAGE: Backups — restore (G12). The row `COVERAGE.md` has carried as
 * `todo` since G7, for the reason this file's project config repeats: a
 * restore runs `DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;`
 * (`_clean_postgresql_schema`, apps/backups/services.py) and then
 * `pg_restore --no-owner` over the result. On the shared instance that lands
 * under every parallel worker mid-run. It needed an instance of its own, and
 * G12 is where there is one.
 *
 * **Both halves of the A/B assertion are load-bearing, and neither is
 * redundant.** A restore that never ran at all still passes "state A is
 * back" — A was never removed. A restore that dropped the schema and failed
 * to load the dump still passes "state B is gone" — everything is gone. Only
 * the two together say a restore happened and restored *this* archive.
 *
 * Assertions poll rather than reading once. `pg_restore` lands under a
 * running application whose connection pool holds sockets to a database whose
 * schema has just been dropped and rebuilt; the first read after that can
 * fail on a stale connection while the state underneath is already correct.
 *
 * **If in-place recovery genuinely does not work, that is a finding to file
 * and pin with `test.fail()` — not a licence to add a container restart until
 * this goes green.** A restore that requires a restart to be observable is a
 * product defect worth a issue, and hiding it behind `instance.restart()`
 * here would convert the one test that could have found it into a test that
 * asserts the workaround.
 */
import { test, expect, ApiClient, Seeder, Waiter } from '../../fixtures';
import type { BackupEntry, Channel, Recording } from '../../fixtures';
import { provisionAdmin } from '../../setup/provision-admin';
import {
  assertAdminTokenStillValid,
  assertDurableState,
  seedDurableState,
} from './durable-state';

type TaskResponse = { task_id: string; task_token: string };

/**
 * `backup_status` does not report Celery's own state vocabulary. It resolves
 * the AsyncResult and re-labels it: `completed` when the task's own dict says
 * so, `failed` on either a task-level error or a Celery failure, and
 * otherwise `result.state.lower()` — so the pending states are lowercase
 * (`pending`, `started`) and the two terminal ones are these.
 *
 * That `failed` label is reachable only for a task that completed and
 * reported its own error. A task that *raised* — a `pg_restore` failure is
 * the likely case here — takes a different path entirely: `backup_status`
 * (`apps/backups/api_views.py`) calls `result.get()` inside a `try`, the
 * exception re-raises there, and the outer `except Exception` turns it into
 * HTTP 500 with `{"detail": ...}`, never `state: 'failed'`. `waitForTask`
 * below treats a non-OK response as informative, not silent: it records the
 * status and body, and gives up after three consecutive 500s rather than
 * polling out the full deadline to report nothing.
 */
type TaskStatus = {
  state?: string;
  error?: string;
  result?: { status?: string; filename?: string; size?: number };
};

async function waitForTask(
  api: ApiClient,
  taskId: string,
  what: string,
  token?: string
): Promise<TaskStatus> {
  // `token`, not `task_token`: the response field and the query parameter
  // have different names (`_verify_task_token` reads
  // `request.query_params.get("token")`).
  const suffix = token ? `?token=${encodeURIComponent(token)}` : '';
  const deadline = Date.now() + 300_000;
  let latest: TaskStatus = {};
  let consecutive500s = 0;
  while (Date.now() < deadline) {
    const res = await api.get(`/api/backups/status/${taskId}/${suffix}`);
    if (res.ok()) {
      consecutive500s = 0;
      latest = (await res.json()) as TaskStatus;
      if (latest.state === 'completed') return latest;
      expect(
        latest.state,
        `${what} failed: ${latest.error ?? JSON.stringify(latest)}`
      ).not.toBe('failed');
    } else {
      // A raised task never reaches `state: 'failed'` above — it surfaces
      // here as a non-OK response instead. Record it so a timeout doesn't
      // report an empty object, and bail early on a run of 500s (the
      // `result.get()` re-raise inside `backup_status`'s own `try`) rather
      // than burning the full 300s deadline to say what a few seconds
      // already showed. A single 500 can be the worker still starting, so
      // this doesn't fire on the first one; other non-OK statuses (a lost
      // session, say) keep polling under the normal deadline.
      latest = { state: `http ${res.status()}`, error: await res.text() };
      if (res.status() === 500) {
        consecutive500s += 1;
        if (consecutive500s >= 3) {
          throw new Error(
            `${what} status endpoint returned 500 three times in a row; last body: ${latest.error}`
          );
        }
      } else {
        consecutive500s = 0;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`${what} did not finish within 300s; last status ${JSON.stringify(latest)}`);
}

// @characterization: pins this deployment's backup format and restore
// mechanism — a pg_dump archive under /data, restored by dropping and
// rebuilding the `public` schema in the container's own PostgreSQL. "A backup
// can be restored" is portable; "the backup is a pg_dump of this database and
// the restore drops this schema" is not. It also destroys and re-provisions
// the container it runs in, which is the CONTAINER_LIFECYCLE capability.
test('a restored backup brings back the state of its instant and discards what came after', { tag: '@characterization' }, async ({
  instance,
  request,
  baseURL,
  upstream,
}, testInfo) => {
  // Own the container AND its volume: a restore is not undoable, and a
  // half-restored database is not a state any other project should inherit.
  // `reset` also recreates the provider (`destroy()` in scripts/e2e_up.sh
  // removes it), so everything below is seeded *after* this call.
  await instance.up({ reset: true });

  try {
    // Not the `api`/`seed` fixtures: those read `playwright/.auth/`, written
    // by `bootstrap`, which this project does not depend on and must not — a
    // persisted pair describes an instance this spec is about to reset.
    const tokens = await provisionAdmin(request, baseURL!);
    const api = new ApiClient(request, tokens);
    // Not the `waitFor` fixture, for the same reason: that Waiter wraps the
    // fixture `api`.
    const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId, new Waiter(api));

    // ---- state A ---------------------------------------------------------
    const state = await seedDurableState(api, seed, upstream);

    const created = await api.json<TaskResponse>(
      await api.post('/api/backups/create/', {}),
      'create a backup'
    );
    const finished = await waitForTask(api, created.task_id, 'the backup');

    // The archive name comes from the finished task, never from `results[0]`
    // of the listing. `create_backup` derives the name from the clock at
    // second granularity and `list_backups` globs the directory newest-first,
    // so indexing the list is the unfiltered-list shape rule 4 forbids —
    // `create_backup_task` returns the filename precisely so a caller need
    // not guess.
    const archiveName = finished.result?.filename;
    expect(
      archiveName,
      `the completed backup task reported no filename: ${JSON.stringify(finished)}`
    ).toBeTruthy();

    // Still confirm it is listed: the task returning a name says the file was
    // written, the listing says the API can see it, and the restore below
    // addresses it by that name.
    const backups = await api.json<BackupEntry[]>(
      await api.get('/api/backups/'),
      'list backups'
    );
    expect(
      backups.map((entry) => entry.name),
      'the created archive is not in the backup listing'
    ).toContain(archiveName);

    // ---- state B: after the backup, so the restore must undo both halves --
    // Half one, an addition the restore must discard.
    const afterBackup = await seed.channel();
    // Half two, a deletion the restore must bring back. The Recording is the
    // cheapest row in state A to remove: nothing cascades off it.
    const deleted = await api.delete(
      `/api/channels/recordings/${state.recording.id}/`
    );
    expect(deleted.ok(), 'could not delete the recording to build state B').toBeTruthy();
    expect(
      (await api.get(`/api/channels/recordings/${state.recording.id}/`)).status(),
      'the recording was still readable after its DELETE, so state B was ' +
        'never actually reached and the restore below would prove nothing'
    ).toBe(404);

    // ---- the restore -----------------------------------------------------
    const restore = await api.json<TaskResponse>(
      await api.post(`/api/backups/${archiveName}/restore/`, {}),
      'restore the backup'
    );
    // `task_token` exists precisely because a restore can invalidate the
    // caller's session — the user table is one of the tables being replaced.
    await waitForTask(api, restore.task_id, 'the restore', restore.task_token);

    // ---- assertions, polled ----------------------------------------------
    await expect
      .poll(
        async () =>
          (await api.get(`/api/channels/recordings/${state.recording.id}/`)).status(),
        {
          message:
            'the recording deleted before the restore did not come back — ' +
            'state A was not restored',
          timeout: 120_000,
        }
      )
      .toBe(200);

    // A is back. `logoBytes: false` — see the gate's comment in
    // durable-state.ts: a version-2 archive carries no files, so the bytes
    // were never in it and were never removed, and asserting them here would
    // pass for the wrong reason.
    await assertAdminTokenStillValid(request, tokens.access);
    await assertDurableState(api, request, state, { logoBytes: false });

    // B is gone.
    await expect
      .poll(async () => (await api.get(`/api/channels/channels/${afterBackup.id}/`)).status(), {
        message:
          `the channel created after the backup (id ${afterBackup.id}) still ` +
          'exists — the archive was not actually loaded over the live database',
        timeout: 120_000,
      })
      .toBe(404);

    // Guard the guard: a 404 for everything would satisfy "B is gone" on its
    // own, so prove the API is still serving state A's rows by id.
    const restored = await api.json<Channel>(
      await api.get(`/api/channels/channels/${state.channel.id}/`),
      'state A channel after the restore'
    );
    expect(restored.uuid).toBe(state.channel.uuid);

    const recording = await api.json<Recording>(
      await api.get(`/api/channels/recordings/${state.recording.id}/`),
      'the restored recording'
    );
    expect(recording.channel).toBe(state.channel.id);
  } finally {
    // Capture the container's logs BEFORE tearing it down — the workflow's
    // `failure()` step runs after teardown has removed the container. Same
    // reasoning, and the same shape, as upgrade-migrations.spec.ts.
    if (testInfo.status !== testInfo.expectedStatus) {
      try {
        await testInfo.attach('container.log', {
          body: await instance.logs(300),
          contentType: 'text/plain',
        });
      } catch (error) {
        console.log(`could not capture container logs: ${String(error)}`);
      }
    }
    try {
      await instance.down();
    } catch (error) {
      // Swallowed deliberately: a throw from `finally` would replace the
      // assertion error that actually explains the run.
      console.log(`could not tear the instance down: ${String(error)}`);
    }
  }
});
