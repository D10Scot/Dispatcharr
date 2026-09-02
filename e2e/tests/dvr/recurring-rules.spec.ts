import { test, expect } from '../../fixtures';
import type { Recording, RecurringRule } from '../../fixtures';

/**
 * Row 7 — the one row in this project that costs no wall clock, because the
 * product materialises a recurring rule's recordings synchronously.
 *
 * `RecurringRecordingRuleViewSet.perform_create` (`apps/channels/api_views.py:3187-3193`):
 *
 *   def perform_create(self, serializer):
 *       rule = serializer.save()
 *       try:
 *           sync_recurring_rule_impl(rule.id, drop_existing=True)
 *       except Exception as err:
 *           logger.warning(f"Failed to initialize recurring rule {rule.id}: {err}")
 *       return rule
 *
 * `sync_recurring_rule_impl` runs inline, in the request thread, before the
 * `201` is returned — no wait or poll is needed after `POST`. Symmetrically,
 * `perform_destroy` (`:3206-3212`) calls `purge_recurring_rule_impl(rule_id)`
 * inline, after the rule row itself is gone — no wait after `DELETE` either.
 *
 * ---------------------------------------------------------------------------
 * Brief vs. source: `start_date`/`end_date` are required on create, and the
 * "14-day horizon" the task's own docstring advertises is unreachable
 * through this API
 * ---------------------------------------------------------------------------
 * The task brief for this row assumed an unqualified "14-day horizon" (citing
 * `sync_recurring_rule_impl`'s `horizon_days: int = 14` default) governs how
 * far a create materialises, and that the resulting row count is 13 or 14.
 * Reading `sync_recurring_rule_impl` (`apps/channels/tasks.py:855-947`) and
 * `RecurringRecordingRuleSerializer.validate` (`apps/channels/serializers.py:833-860`)
 * together shows two corrections:
 *
 *  1. `validate()` requires `start_date` and `end_date` on create — quoting
 *     `:838-841` and `:844-847`:
 *
 *       if start_date is None:
 *           existing_start = getattr(self.instance, "start_date", None)
 *           if existing_start is None:
 *               raise serializers.ValidationError("Start date is required")
 *       ...
 *       if end_date is None:
 *           existing_end = getattr(self.instance, "end_date", None)
 *           if existing_end is None:
 *               raise serializers.ValidationError("End date is required")
 *
 *     `self.instance` is `None` on a `POST`, so both fields are mandatory —
 *     omitting either 400s. `apps/channels/tests/test_recurring_rules.py`'s
 *     only rule fixture never surfaces this because it constructs
 *     `RecurringRecordingRule.objects.create(...)` directly via the ORM,
 *     bypassing the serializer's `validate()` entirely.
 *
 *  2. Once `end_date` is supplied (as it must be), the horizon never applies.
 *     Quoting `sync_recurring_rule_impl` (`tasks.py:882-889`):
 *
 *       horizon = now + timedelta(days=horizon_days)
 *       start_window = max(start_limit, local_today)
 *       if drop_existing and end_limit:
 *           end_window = end_limit
 *       else:
 *           end_window = horizon.astimezone(tz).date()
 *           if end_limit and end_window < end_limit:
 *               end_window = end_limit
 *
 *     `perform_create` always calls with `drop_existing=True`, and — per (1)
 *     — `end_limit` (`rule.end_date`) is always set on a rule created
 *     through the API. So the `if drop_existing and end_limit` branch is the
 *     one that always runs from this endpoint: `end_window = end_limit`,
 *     the caller's own `end_date`, completely unbounded by `horizon_days`.
 *     The `horizon`-driven `else` branch — the one the task's docstring
 *     ("Ensure recordings exist... within the scheduling horizon") and this
 *     row's brief both describe — is dead from the REST API; it only runs
 *     for a rule with no `end_date`, which `validate()` forbids on create,
 *     and `perform_update` (`:3195-3204`) also always passes
 *     `drop_existing=True`. Worth a `COVERAGE.md` note for Task 10: as
 *     shipped, an API-created recurring rule's materialisation window is
 *     bounded by the caller's own `end_date`, not by any system horizon —
 *     which also means a rule created with a far-future `end_date` would
 *     materialise every matching day between now and then synchronously, in
 *     one request, with nothing capping it.
 *
 *     This test reproduces the row count the brief wanted by choosing its
 *     own `end_date` 14 days out — deliberately, not because the endpoint
 *     enforces it. `start_date` is set two days in the past (safely before
 *     "today" in any timezone this suite could be running relative to the
 *     system's configured one) so `start_window` above resolves to
 *     `local_today` regardless of clock skew between this process and the
 *     container.
 *
 * ---------------------------------------------------------------------------
 * The row count: 14 or 15, not 13 or 14
 * ---------------------------------------------------------------------------
 * With `start_date` in the past and `end_date` = "today" + 14 (both in the
 * system timezone), `start_window` = `local_today` and `end_window` =
 * `end_date`, so the loop (`tasks.py:894-895`) walks
 * `range((end_window - start_window).days + 1)` = `range(15)` — 15
 * candidate calendar dates, `local_today` through `local_today + 14`
 * inclusive. With all seven weekdays in the rule, every one of those 15
 * dates matches (`tasks.py:896`). The only thing that can drop a candidate
 * is `if start_dt <= now: continue` (`:907`) — which only ever fires for
 * `local_today` itself (every later date's combined datetime is already in
 * the future no matter what time of day the suite runs). So the row count
 * is **14** (today's slot already past when the sync ran) or **15**
 * (today's slot still ahead) — never 13. This test asserts that range and
 * says why here rather than pinning a number that flips depending on the
 * hour it runs.
 *
 * `start_time`/`end_time` are fixed at system-timezone noon/13:00 — roughly
 * the middle of the day, so which of the two counts a given run lands on
 * genuinely depends on wall-clock time, exercising both branches of the
 * skip logic across different runs rather than pinning one. This does carry
 * one inherent, unavoidable low-probability race, not introduced by this
 * choice: if the suite happens to run within a few seconds either side of
 * system-timezone noon, the row materialised for "today" could cross from
 * not-yet-started to already-started between the `POST` (materialisation)
 * and the `DELETE` (purge) a few lines later — `purge_recurring_rule_impl`
 * filters `start_time__gte=now` (`tasks.py:844-847`), so a slot that has
 * *just* ticked into the past by purge time would be silently left behind.
 * No fixed clock-of-day value can avoid this — any two chosen times still
 * have a boundary, and it is not what this row exists to test.
 *
 * Model for this file: `recording-events.spec.ts` — explicit-channel
 * scenario via `seed.upstreamChannel`, module-scoped ids captured as they
 * resolve, `afterEach` cleanup. Unlike that file, this row needs no `ws`, no
 * upstream connection and no HLS — the whole row is REST-surface only, which
 * is also why it costs no wall clock.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const SYSTEM_SETTINGS_KEY = 'system_settings';
const RECORDINGS_PATH = '/api/channels/recordings/';
const RECURRING_RULES_PATH = '/api/channels/recurring-rules/';

/** Monday=0..Sunday=6 — `RecurringRecordingRuleSerializer.validate_days_of_week`'s numbering, matching Python's `date.weekday()`. */
const WEEKDAY_INDEX: Record<string, number> = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };

/** `date`'s weekday (Monday=0..Sunday=6) as it falls in `tz` — mirrors `target_date.weekday()` in `sync_recurring_rule_impl` (`tasks.py:896`), computed for a specific instant rather than a bare calendar date. */
function weekdayInTz(date: Date, tz: string): number {
  const short = new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short' }).format(date);
  const idx = WEEKDAY_INDEX[short];
  expect(idx, `unrecognised weekday short-name "${short}" for tz ${tz}`).toBeDefined();
  return idx;
}

/** Today's date in `tz`, as `YYYY-MM-DD` — mirrors `now.astimezone(tz).date()` (`tasks.py:879`). `en-CA` is the standard trick for an ISO-shaped `Intl` date string. */
function todayInTz(tz: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    new Date()
  );
}

/** Pure calendar-date arithmetic on a `YYYY-MM-DD` string — deliberately routed through `Date.UTC` so it never touches a real timezone's DST transitions. */
function addCalendarDays(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

let channelIdToCleanup: number | undefined;
let ruleIdToCleanup: number | undefined;

test.afterEach(async ({ api }, testInfo) => {
  const ruleId = ruleIdToCleanup;
  const channelId = channelIdToCleanup;
  ruleIdToCleanup = undefined;
  channelIdToCleanup = undefined;
  if (ruleId === undefined && channelId === undefined) return;

  try {
    if (ruleId !== undefined) {
      // The test body deletes this rule itself (that's the thing under
      // test), so a 404 here is the expected already-cleaned-up case, not a
      // cleanup failure — same shape as recording-events.spec.ts.
      const res = await api.delete(`${RECURRING_RULES_PATH}${ruleId}/`);
      if (res.status() !== 204 && res.status() !== 404) {
        throw new Error(`recurring rule cleanup failed: DELETE returned ${res.status()}`);
      }
    }
    if (channelId !== undefined) {
      const res = await api.delete(`/api/channels/channels/${channelId}/`);
      if (res.status() !== 204 && res.status() !== 404) {
        throw new Error(`channel cleanup failed: DELETE returned ${res.status()}`);
      }
    }
  } catch (cleanupError) {
    if (testInfo.status !== 'passed') {
      console.error(
        'recurring-rules.spec.ts: cleanup failed after an in-flight test ' +
          'failure — not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

test(
  'a recurring rule materialises its recordings synchronously on create and purges them on delete',
  { tag: '@contract' },
  async ({ upstream, seed, api }) => {
    const scenario = await upstream.scenario({
      channels: [{ id: 1, name: 'G13 DVR Recurring Rule', tvgId: 'g13-dvr-recurring.e2e', logo: null }],
    });
    const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1] });
    channelIdToCleanup = channel.id;

    // Read the system timezone honestly (CoreSettings.get_system_time_zone(),
    // core/models.py:738-739) — never write it, per the file header and this
    // row's brief: it is a global row shared with every other test.
    const settingsRows = await api.json<Array<{ id: number; key: string; value: Record<string, unknown> }>>(
      await api.get(CORE_SETTINGS_PATH),
      'core settings'
    );
    const systemSettingsRow = settingsRows.find((r) => r.key === SYSTEM_SETTINGS_KEY);
    expect(systemSettingsRow, `the "${SYSTEM_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
    const tzName = (systemSettingsRow!.value.time_zone as string) || 'UTC';

    const today = todayInTz(tzName);
    // See the file header: two days in the past so start_window resolves to
    // local_today regardless of clock skew, and 14 days out so end_window
    // reproduces the brief's intended ~2-week materialisation window (the
    // endpoint itself does not cap this — see the file header).
    const startDate = addCalendarDays(today, -2);
    const endDate = addCalendarDays(today, 14);

    // ------------------------------------------------------------------
    // Step 1: create the rule and assert the materialisation
    // ------------------------------------------------------------------
    const createRes = await api.post(RECURRING_RULES_PATH, {
      channel: channel.id,
      days_of_week: [0, 1, 2, 3, 4, 5, 6],
      start_time: '12:00:00',
      end_time: '13:00:00',
      start_date: startDate,
      end_date: endDate,
      name: 'G13 DVR Recurring Rule',
    });
    expect(createRes.status(), `POST returned ${createRes.status()}: ${await createRes.text()}`).toBe(201);
    const rule = await api.json<RecurringRule>(createRes, 'create recurring rule');
    ruleIdToCleanup = rule.id;

    // sync_recurring_rule_impl runs inline inside perform_create, before the
    // 201 above is even returned — no wait or poll needed here.
    const listRes = await api.get(RECORDINGS_PATH);
    const allRecordings = await api.json<Recording[]>(listRes, 'list recordings after create');
    const ruleRecordings = allRecordings.filter((r) => {
      const cp = (r.custom_properties ?? {}) as Record<string, any>;
      return r.channel === channel.id && cp.rule?.id === rule.id;
    });

    // See the file header for why this is 14 or 15, never 13.
    expect(
      ruleRecordings.length,
      `expected 14 or 15 materialised recordings for rule ${rule.id}, got ${ruleRecordings.length}`
    ).toBeGreaterThanOrEqual(14);
    expect(
      ruleRecordings.length,
      `expected 14 or 15 materialised recordings for rule ${rule.id}, got ${ruleRecordings.length}`
    ).toBeLessThanOrEqual(15);

    const now = Date.now();
    const weekdaysSeen = new Set<number>();
    for (const recording of ruleRecordings) {
      const cp = recording.custom_properties as Record<string, any>;

      // The start_dt <= now skip (tasks.py:907) — every materialised row is
      // still ahead of "now".
      expect(
        new Date(recording.start_time).getTime(),
        `recording ${recording.id} start_time ${recording.start_time} should be in the future`
      ).toBeGreaterThan(now);

      // custom_properties shape stamped by sync_recurring_rule_impl (tasks.py:917-925).
      expect(cp.status).toBe('scheduled');
      expect(cp.rule?.id).toBe(rule.id);
      expect([...(cp.rule?.days_of_week ?? [])].sort((a: number, b: number) => a - b)).toEqual([
        0, 1, 2, 3, 4, 5, 6,
      ]);

      // Every row's weekday (computed in the system tz, matching
      // target_date.weekday() at tasks.py:896) falls in the rule's day set —
      // trivial for an all-seven-days rule (every value 0-6 qualifies), but
      // collected below to additionally prove the mapping produces real
      // variety across the window, not just one repeated day.
      const weekday = weekdayInTz(new Date(recording.start_time), tzName);
      expect(cp.rule?.days_of_week).toContain(weekday);
      weekdaysSeen.add(weekday);
    }
    // 14 or 15 consecutive calendar dates always span at least two full
    // weeks' worth of distinct weekdays, so with all seven days enabled,
    // every weekday must appear at least once — the sharper property the
    // brief flagged as needing a narrower day-set rule to prove is, for the
    // all-seven case, still fully provable this way. A rule with a narrower
    // set remains the sharper test in general and stays a COVERAGE.md gap
    // for Task 10.
    expect(
      [...weekdaysSeen].sort((a, b) => a - b),
      `expected all 7 weekdays represented, saw ${[...weekdaysSeen].sort((a, b) => a - b).join(',')}`
    ).toEqual([0, 1, 2, 3, 4, 5, 6]);

    // ------------------------------------------------------------------
    // Step 3: assert the purge (also this row's own cleanup)
    // ------------------------------------------------------------------
    const deleteRuleRes = await api.delete(`${RECURRING_RULES_PATH}${rule.id}/`);
    expect(deleteRuleRes.status(), `DELETE returned ${deleteRuleRes.status()}: ${await deleteRuleRes.text()}`).toBe(
      204
    );

    // purge_recurring_rule_impl runs inline inside perform_destroy, after
    // the rule row is already gone — no wait needed here either.
    const afterListRes = await api.get(RECORDINGS_PATH);
    const afterRecordings = await api.json<Recording[]>(afterListRes, 'list recordings after purge');
    const stillPresent = ruleRecordings.filter((created) => afterRecordings.some((r) => r.id === created.id));
    expect(
      stillPresent.map((r) => r.id),
      'every recording materialised in Step 1 should be gone after the rule is deleted'
    ).toEqual([]);
  }
);
