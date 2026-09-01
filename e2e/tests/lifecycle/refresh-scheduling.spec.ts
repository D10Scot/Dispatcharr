/**
 * Refresh scheduling: interval, cron, and the beat rows behind both.
 *
 * COVERAGE: Sources — refresh-interval scheduling (G12). `todo` since G3,
 * whose D10 recorded the reason: a non-zero `refresh_interval` makes
 * `create_or_update_periodic_task` compute
 * `should_be_enabled = enabled and (use_cron or interval_hours > 0)`, so the
 * instance is left with an ENABLED hourly beat task re-refreshing that
 * account for the life of the container. The shared `seeded` instance cannot
 * tolerate that, and neither can the other lifecycle projects — the provider
 * forgets its scenarios across a restart, so a background refresh would
 * mutate rows under their durable-state assertions. This project exists to
 * give those rows somewhere to live.
 *
 * **Nothing here waits for a tick.** The interval branch does
 * `IntervalSchedule.objects.get_or_create(every=max(int(interval_hours), 1)
 * ..., period=HOURS)`, so the smallest schedulable unit is one hour. Every
 * assertion below is about the schedule that was *written*, never about it
 * firing.
 *
 * The two tests split on observability, deliberately (spec D19):
 *
 *  - Test 1 is REST only, and its assertions are the portable ones.
 *  - Test 2 reads django-celery-beat's own tables through `dumpdata`, because
 *    `PeriodicTask.enabled`, `IntervalSchedule.every` and orphan cleanup have
 *    no REST surface at all.
 */
import { test, expect, ApiClient, Seeder, Waiter } from '../../fixtures';
import type { EpgSource, M3uAccount } from '../../fixtures';
import { provisionAdmin } from '../../setup/provision-admin';

/**
 * Hours. Two values, both non-zero so that `should_be_enabled` is true.
 *
 * These are the one exception to `e2e/README.md`'s uniqueness rule for
 * non-zero `refresh_interval` values, and only because of where they run —
 * see that section, which states the exemption and what would revoke it.
 */
const INTERVAL_HOURS = 8541;
const INTERVAL_HOURS_AFTER = 8542;

/** A 5-part expression; the values are arbitrary and only have to round-trip. */
const CRON = '17 3 * * 1';

type BeatRow = {
  model: string;
  pk: number;
  fields: Record<string, unknown>;
};

/**
 * `manage.py` prints a banner to stdout before the payload, so parse from the
 * first `[` rather than trusting the whole stream to be JSON.
 *
 * The argument array passes `Instance.manage`'s filter intact — every token
 * matches `^[A-Za-z0-9._/=-]+$` — and contains none of
 * CONTAINER_INTROSPECTION's three literals (`pgrep`, `docker `, `manage.py`),
 * so this needs no capability beyond the CONTAINER_LIFECYCLE this file
 * already declares.
 */
async function beatRows(instance: {
  manage: (argv: string[]) => Promise<{ stdout: string }>;
}): Promise<BeatRow[]> {
  const { stdout } = await instance.manage([
    'dumpdata',
    'django_celery_beat.PeriodicTask',
    'django_celery_beat.IntervalSchedule',
    'django_celery_beat.CrontabSchedule',
    '--format=json',
  ]);
  const start = stdout.indexOf('[');
  expect(start, `dumpdata produced no JSON array:\n${stdout}`).toBeGreaterThanOrEqual(0);
  return JSON.parse(stdout.slice(start)) as BeatRow[];
}

// @characterization: the tag is fixed by this file owning and resetting a
// container (the CONTAINER_LIFECYCLE capability), not by the assertions
// below, which are the portable ones: `refresh_interval` and
// `cron_expression` are REST round-trips that any behaviour-preserving
// rewrite must keep working. A different scheduler behind the same API would
// leave this test green, which is exactly what makes it the portable half of
// the pair.
test('refresh interval and cron expression round-trip through the API', { tag: '@characterization' }, async ({
  instance,
  request,
  baseURL,
}, testInfo) => {
  await instance.up({ reset: true });

  // Not the `api`/`seed` fixtures: those read `playwright/.auth/`, written by
  // `bootstrap`, which this project does not depend on and must not — a
  // persisted pair describes an instance this spec is about to reset.
  const tokens = await provisionAdmin(request, baseURL!);
  const api = new ApiClient(request, tokens);
  // Not the `waitFor` fixture, for the same reason: that Waiter wraps the
  // fixture `api`.
  const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId, new Waiter(api));

  const account = await seed.m3uAccount({ refresh_interval: INTERVAL_HOURS });
  const source = await seed.epgSource({ refresh_interval: INTERVAL_HOURS });

  for (const [label, url, id] of [
    ['M3U account', '/api/m3u/accounts', account.id],
    ['EPG source', '/api/epg/sources', source.id],
  ] as const) {
    // 1. The interval persisted rather than being coerced.
    const created = await api.json<M3uAccount | EpgSource>(
      await api.get(`${url}/${id}/`),
      `read back ${label}`
    );
    expect(
      created.refresh_interval,
      `${label}: refresh_interval did not persist as written`
    ).toBe(INTERVAL_HOURS);

    // 2. A cron expression round-trips.
    //
    // NOT a tautology, and it matters that a reader knows why:
    // `cron_expression` is not a model field. Both serializers declare it a
    // plain CharField and rebuild it in `to_representation` from
    // `instance.refresh_task.crontab` — their own comments call that the
    // "single source of truth". So reading back the expression just written
    // proves a CrontabSchedule row was created, linked to the PeriodicTask,
    // and decomposed into the five fields the schedule stores. A reader who
    // assumes it is a stored column would conclude this proves nothing.
    await api.json(
      await api.patch(`${url}/${id}/`, { cron_expression: CRON }),
      `set cron on ${label}`
    );
    const cronned = await api.json<{ cron_expression: string }>(
      await api.get(`${url}/${id}/`),
      `read back cron on ${label}`
    );
    expect(
      cronned.cron_expression,
      `${label}: the cron expression did not round-trip, so no CrontabSchedule ` +
        'was created and linked'
    ).toBe(CRON);

    // 3. Switching back to an interval clears the crontab.
    await api.json(
      await api.patch(`${url}/${id}/`, {
        refresh_interval: INTERVAL_HOURS_AFTER,
        cron_expression: '',
      }),
      `switch ${label} back to an interval`
    );
    const reverted = await api.json<{ cron_expression: string; refresh_interval: number }>(
      await api.get(`${url}/${id}/`),
      `read back ${label} after reverting to an interval`
    );
    expect(
      reverted.cron_expression,
      `${label}: cron_expression is still set, so the PeriodicTask kept its ` +
        'crontab and the account is on the wrong schedule'
    ).toBe('');
    expect(reverted.refresh_interval).toBe(INTERVAL_HOURS_AFTER);
  }
});

// @characterization: couples to django-celery-beat's table names and to the
// AIO container layout, because the product exposes no other view of
// `PeriodicTask.enabled`, `IntervalSchedule.every` or orphan cleanup. A
// rewrite that preserved every behaviour but changed scheduler is EXPECTED to
// change this test. It is the one test in G12 where the tag is right on the
// assertions' own merits rather than by the file's container ownership.
test('the beat rows behind a schedule are created, enabled and cleaned up', { tag: '@characterization' }, async ({
  instance,
  request,
  baseURL,
}, testInfo) => {
  // `up()` without `reset`, and it is needed despite this project being
  // serial. The `instance` fixture is per-TEST, and its teardown calls
  // `down()` whenever that test took ownership (`inst.owned`, set by
  // `up({ reset: true })`) — so test 1's container is gone by the time this
  // one starts, and the plan's "the second test runs against the state the
  // first left" does not hold. No `reset` here: this test seeds every row it
  // asserts on and addresses them all by name or id, so adopting a container
  // that is already up is both correct and a boot cheaper.
  await instance.up();

  const tokens = await provisionAdmin(request, baseURL!);
  const api = new ApiClient(request, tokens);
  const seed = new Seeder(api, testInfo.workerIndex, testInfo.testId, new Waiter(api));

  // `is_active: true` on both, so that the ONLY difference between them is
  // the interval. It is also required for either task to be enabled at all:
  // `should_be_enabled` in core/scheduling.py is
  // `enabled and (use_cron or interval_hours > 0)`, and the `enabled`
  // argument is not a constant — apps/epg/signals.py passes
  // `should_be_enabled = instance.is_active`. Both halves must hold. Since
  // `seed.epgSource` defaults `is_active` to false, a source created with a
  // non-zero interval and nothing else gets a DISABLED task, which is not
  // the fact this test is trying to pin.
  const scheduled = await seed.epgSource({
    refresh_interval: INTERVAL_HOURS,
    is_active: true,
  });
  // The other side of `should_be_enabled`, and the reason every other project
  // in this suite can use 0 freely: it yields a DISABLED task even though the
  // source is active.
  const unscheduled = await seed.epgSource({ refresh_interval: 0, is_active: true });

  const rows = await beatRows(instance);
  const tasks = rows.filter((row) => row.model === 'django_celery_beat.periodictask');
  const intervals = rows.filter((row) => row.model === 'django_celery_beat.intervalschedule');

  // `epg_source-refresh-<id>`, from apps/epg/signals.py.
  const scheduledTask = tasks.find((t) => t.fields.name === `epg_source-refresh-${scheduled.id}`);
  expect(
    scheduledTask,
    `no PeriodicTask named epg_source-refresh-${scheduled.id}. Names present: ` +
      tasks.map((t) => String(t.fields.name)).join(', ')
  ).toBeDefined();
  expect(
    scheduledTask!.fields.enabled,
    'the task for a non-zero refresh_interval is disabled — should_be_enabled ' +
      'is `enabled and (use_cron or interval_hours > 0)`, so this should be true'
  ).toBe(true);

  const interval = intervals.find((row) => row.pk === scheduledTask!.fields.interval);
  expect(
    interval,
    `the task's interval ${String(scheduledTask!.fields.interval)} resolves to no IntervalSchedule`
  ).toBeDefined();
  // `every=max(int(interval_hours), 1) if interval_hours else 1`, period=HOURS.
  expect(interval!.fields.every).toBe(INTERVAL_HOURS);
  expect(interval!.fields.period).toBe('hours');

  const unscheduledTask = tasks.find(
    (t) => t.fields.name === `epg_source-refresh-${unscheduled.id}`
  );
  expect(
    unscheduledTask,
    `no PeriodicTask named epg_source-refresh-${unscheduled.id}`
  ).toBeDefined();
  expect(
    unscheduledTask!.fields.enabled,
    'refresh_interval 0 with no cron produced an ENABLED task on an ACTIVE ' +
      'source — the whole rest of the suite relies on 0 being inert'
  ).toBe(false);

  // Deleting the source removes its task, and the now-unreferenced schedule
  // with it (`_cleanup_orphaned_interval`).
  const intervalPk = interval!.pk;
  expect((await api.delete(`/api/epg/sources/${scheduled.id}/`)).ok()).toBeTruthy();

  const after = await beatRows(instance);
  expect(
    after
      .filter((row) => row.model === 'django_celery_beat.periodictask')
      .map((t) => String(t.fields.name)),
    'the PeriodicTask outlived the source it refreshes'
  ).not.toContain(`epg_source-refresh-${scheduled.id}`);

  // Only assert the schedule is gone if nothing else still points at it: the
  // interval rows are shared by `get_or_create`, and the unscheduled source
  // above holds `every=1`, not this one.
  const stillReferenced = after
    .filter((row) => row.model === 'django_celery_beat.periodictask')
    .some((t) => t.fields.interval === intervalPk);
  if (!stillReferenced) {
    expect(
      after
        .filter((row) => row.model === 'django_celery_beat.intervalschedule')
        .map((row) => row.pk),
      'the IntervalSchedule was left orphaned — _cleanup_orphaned_interval ' +
        'did not remove a schedule nothing references'
    ).not.toContain(intervalPk);
  }
});
