import { test, expect } from '../../fixtures';
import type { M3uFilterOverrides, StreamPage } from '../../fixtures';

/**
 * `M3UFilter` — exclude, first-match-wins include, and `order` precedence.
 *
 * The whole contract lives in two functions in `apps/m3u/tasks.py`:
 *
 * - `_compile_m3u_stream_filters` (`:1008-1018`) compiles a queryset of
 *   `M3UFilter` rows into `(pattern, filter_obj)` pairs, in whatever order
 *   its caller hands it — both call sites order that queryset by `order`
 *   (`account.filters.order_by("order")`, `:1296` and `:3402-3403`), which is
 *   what makes test 18's ordering premise hold. It sets
 *   `re.IGNORECASE` **only** when `custom_properties["case_sensitive"] is
 *   False` — the flag's *absence* (as in every test below, which never sets
 *   `custom_properties`) means case-sensitive matching, not
 *   case-insensitive.
 * - `_stream_passes_m3u_filters` (`:1021-1038`) walks the compiled filters in
 *   that same order and, on the **first** pattern that matches, returns
 *   `not filter_obj.exclude` immediately — it never looks at any filter
 *   after the first match. A stream matching **no** filter falls through the
 *   loop and returns `True` (passes) by default. So `exclude: false` is
 *   first-match-wins, not a whitelist: it does not exclude everything that
 *   fails to match it, and a second, later filter that would also match is
 *   never even reached once an earlier one already has.
 *
 * Filters are applied on both places `apps/m3u/tasks.py:_refresh_single_m3u_account_impl`
 * fans work out to `process_m3u_batch_direct` via `executor.submit(...)`
 * (`:3588-3589` for the standard M3U path, `:3726-3727` for the XC path).
 * This file exercises the standard M3U path only.
 *
 * ---------------------------------------------------------------------------
 * The ordering constraint every test here is built around
 * ---------------------------------------------------------------------------
 * `M3UFilterViewSet.perform_create` (`apps/m3u/api_views.py:593-604`) takes
 * the owning account's id from the URL (`/api/m3u/accounts/<id>/filters/`),
 * so a filter can only be created once its account already exists.
 * `Seeder.m3uAccount()` already defaults `is_active: false`
 * (`e2e/fixtures/seed.ts:223-231`) — every test below still passes it
 * explicitly, for readability, not because the default would otherwise let
 * something slip through. The actual hazard is `refresh_account_on_save`
 * (`apps/m3u/signals.py:12-20`): it queues a create-time `refresh_m3u_groups`
 * refresh for **every** newly-created non-XC account regardless of
 * `is_active` — the signal itself never reads that field. What stops that
 * create-time task from running unfiltered against an inactive account is
 * the task's own account lookup (`apps/m3u/tasks.py:1552-1556`,
 * `M3UAccount.objects.get(id=..., is_active=True)`), which raises
 * `DoesNotExist` and writes nothing while the account stays inactive. So
 * every test here creates the account **inactive** first, creates the
 * filter(s) against it, and only then `PATCH`es `is_active: true` and
 * triggers the real refresh — the first refresh this account ever runs is
 * the filtered one. (`seed.upstreamM3UAccount()`, which this file
 * deliberately does not use, is the one seeder factory that overrides the
 * default to `is_active: true` — exactly why it is unsafe for this file's
 * ordering.)
 *
 * That `PATCH` does not itself race a second refresh: `refresh_account_on_save`
 * only fires on `created`, never on update, so flipping `is_active` queues
 * no refresh of its own — `waitFor.m3uRefreshComplete()`'s own trigger
 * (`POST /api/m3u/refresh/<id>/`) is the only refresh explicitly triggered
 * here. That also means `seed.waitForCreateTimeGroupRefreshToSettle()` (see
 * `m3u-ingest.spec.ts`) is unnecessary here: it exists to out-wait a
 * create-time task that *does* reach a terminal write, because
 * `upstreamM3UAccount()` creates its account active. Here, provided the
 * create-time `refresh_m3u_groups` task executes before the activating
 * `PATCH` — which two HTTP round-trips make near-certain — its own
 * `is_active=True` lookup raises `DoesNotExist` and it writes nothing. If it
 * is instead delayed past the `PATCH` (a busy Celery queue under parallel
 * `seeded` workers), it finds the account active and writes `status:
 * 'pending_setup'` under a separate lock (`refresh_m3u_account_groups`,
 * `apps/m3u/tasks.py:1546`) from the explicitly-triggered refresh below — a
 * write `waitFor.m3uRefreshComplete()` could observe as its baseline or as
 * the in-flight status. The filter already exists by then either way, so
 * this file's assertions still hold; the exposure is a flakier wait, not a
 * wrong verdict.
 */

/** Escapes every {@link https://tc39.es/ecma262/#sec-patterns regex metacharacter} in `value`. */
function escapeForRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test(
  'an M3UFilter with exclude: true keeps the matching stream out of the ingest',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor }) => {
    test.setTimeout(120_000);

    const prefix = seed.generatedName('m3u-filter-exclude');
    const declared = [1, 2, 3].map((id) => ({
      id,
      name: `${prefix}-ch${id}`,
      tvgId: `${prefix}-ch${id}.e2e`,
      logo: null,
    }));
    const scenario = await upstream.scenario({ channels: declared });

    // Inactive: see the file header for why the filter must exist before
    // this account's first refresh ever runs.
    const account = await seed.m3uAccount({
      is_active: false,
      refresh_interval: 0,
      server_url: upstream.playlistUrl(scenario),
    });

    const excludedName = declared[0].name;
    // `escapeForRegex` guards against generatedName's own output: the name
    // contains literal `.` characters (from `generatedName`'s `sanitise`,
    // which keeps `.` verbatim), and an unescaped `.` in a regex pattern
    // matches any character, not just itself.
    const filterBody: M3uFilterOverrides = {
      filter_type: 'name',
      regex_pattern: escapeForRegex(excludedName),
      exclude: true,
      order: 0,
    };
    const createdFilter = await api.post(`/api/m3u/accounts/${account.id}/filters/`, filterBody);
    expect(createdFilter.status()).toBe(201);

    const activated = await api.patch(`/api/m3u/accounts/${account.id}/`, { is_active: true });
    expect(activated.ok()).toBeTruthy();

    const refreshed = await waitFor.m3uRefreshComplete(account.id);
    expect(refreshed.status).toBe('success');

    // Scoped to this account — a legitimate count under G3's D13, per the brief.
    const page = await api.json<StreamPage>(
      await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
      'streams ingested by this filtered account'
    );
    const names = page.results.map((s) => s.name);
    expect(names).not.toContain(excludedName);
    expect(names).toContain(declared[1].name);
    expect(names).toContain(declared[2].name);
    expect(page.count).toBe(2);
  }
);

test(
  'an M3UFilter with exclude: false is first-match-wins, not a whitelist',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor }) => {
    test.setTimeout(120_000);

    const prefix = seed.generatedName('m3u-filter-include');
    const declared = [1, 2, 3].map((id) => ({
      id,
      name: `${prefix}-ch${id}`,
      tvgId: `${prefix}-ch${id}.e2e`,
      logo: null,
    }));
    const scenario = await upstream.scenario({ channels: declared });

    const account = await seed.m3uAccount({
      is_active: false,
      refresh_interval: 0,
      server_url: upstream.playlistUrl(scenario),
    });

    const matchedName = declared[0].name;
    const filterBody: M3uFilterOverrides = {
      filter_type: 'name',
      regex_pattern: escapeForRegex(matchedName),
      exclude: false,
      order: 0,
    };
    const createdFilter = await api.post(`/api/m3u/accounts/${account.id}/filters/`, filterBody);
    expect(createdFilter.status()).toBe(201);

    const activated = await api.patch(`/api/m3u/accounts/${account.id}/`, { is_active: true });
    expect(activated.ok()).toBeTruthy();

    const refreshed = await waitFor.m3uRefreshComplete(account.id);
    expect(refreshed.status).toBe('success');

    const page = await api.json<StreamPage>(
      await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
      'streams ingested by this filtered account'
    );
    const names = page.results.map((s) => s.name);

    // Half one: the matched stream's first (and only) match returned
    // `not exclude` -> True, so it survived.
    expect(names).toContain(matchedName);
    // Half two — the distinction this test exists to pin: the other two
    // streams matched nothing at all and fell through
    // `_stream_passes_m3u_filters`'s loop to its default `return True`.
    // Asserting only the line above would pass just as well on a whitelist
    // implementation (one that excluded everything NOT matched by an
    // `exclude: false` filter); asserting these two survived too is what
    // rules that reading out.
    expect(names).toContain(declared[1].name);
    expect(names).toContain(declared[2].name);
    expect(page.count).toBe(3);
  }
);

test(
  'order decides which of two matching filters governs a stream',
  { tag: '@contract' },
  async ({ upstream, seed, api, waitFor }) => {
    test.setTimeout(120_000);

    const prefix = seed.generatedName('m3u-filter-order');
    const declared = [1, 2, 3].map((id) => ({
      id,
      name: `${prefix}-ch${id}`,
      tvgId: `${prefix}-ch${id}.e2e`,
      logo: null,
    }));
    const scenario = await upstream.scenario({ channels: declared });

    const account = await seed.m3uAccount({
      is_active: false,
      refresh_interval: 0,
      server_url: upstream.playlistUrl(scenario),
    });

    const targetName = declared[0].name;
    const pattern = escapeForRegex(targetName);

    // Both filters match the same stream. `order: 0`'s `exclude: false`
    // matches first and returns `not exclude` -> True immediately —
    // `_stream_passes_m3u_filters`'s loop returns on the FIRST match, so
    // `order: 1`'s `exclude: true` is never reached for this stream. If the
    // loop instead let a later, more specific match win, this stream would
    // be excluded.
    const includeFirst: M3uFilterOverrides = {
      filter_type: 'name',
      regex_pattern: pattern,
      exclude: false,
      order: 0,
    };
    const excludeSecond: M3uFilterOverrides = {
      filter_type: 'name',
      regex_pattern: pattern,
      exclude: true,
      order: 1,
    };
    const createdInclude = await api.post(
      `/api/m3u/accounts/${account.id}/filters/`,
      includeFirst
    );
    expect(createdInclude.status()).toBe(201);
    const createdExclude = await api.post(
      `/api/m3u/accounts/${account.id}/filters/`,
      excludeSecond
    );
    expect(createdExclude.status()).toBe(201);

    const activated = await api.patch(`/api/m3u/accounts/${account.id}/`, { is_active: true });
    expect(activated.ok()).toBeTruthy();

    const refreshed = await waitFor.m3uRefreshComplete(account.id);
    expect(refreshed.status).toBe('success');

    const page = await api.json<StreamPage>(
      await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
      'streams ingested by this filtered account'
    );
    const names = page.results.map((s) => s.name);
    expect(names).toContain(targetName);
    expect(page.count).toBe(3);
  }
);
