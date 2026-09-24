# Fix plan, category E — backend correctness

**Category.** E: twenty-two tracker issues, twenty distinct defects, where Django-side code does the
wrong thing on an ordinary path: a cache cleared on the wrong class, a setting read from a row that
no longer exists, a status that says "success" or "download failed" when neither happened, a
`get_or_create` against a table with no uniqueness, a serializer declaration DRF never reads. None of
them is a crash on hostile input (that is category C) and none is a security boundary (category B).
Two issues are closed duplicates (#297 of #177, #6 of #7) and one (#71) is frontend-only.

**Seed SHA: `a54b09a9`** (`main`, 2026-09-23). Every `file:line` below was opened there. Ten of the
root causes were also reproduced there, in a private test container (`fixplan-E`, bind-mounted at
this plan's worktree) with a throwaway probe module that was deleted afterwards; the measured value
is quoted in each issue's "Reproduced at seed" line.

**Ordering position.** Sixth of ten: B, A, J, C, D, **E**, G, H, I, F. The lead re-seeds this plan
when an earlier category's plan merges. Three PRs here must wait for an earlier plan to *merge*, not
merely to be written: E-2 waits for J-1 and J-3, E-5 waits for C-3, E-7 waits for B-2 and C-1.
One more waits for the user rather than a plan: E-9 (#138) starts only after open question Q2 is
answered, because its default reverses a deliberate upstream change. The
overlap section says why.

**Architecture.** Django 6 + DRF control plane with Celery workers and Celery beat (database
scheduler, `django_celery_beat`). The live relay is the Go binary in `relay/` and is untouched here.
Every fix in this plan is Django-side Python, one Django migration, or one frontend utility.

**Tech stack.** Python 3.13, Django 6, DRF, `django_celery_beat`, `djangorestframework-simplejwt`
5.5.1, React 19 + vitest for the one frontend change.

**Planner's worktree.** `.worktrees/fixplan-E`, branch `docs/fixplan-E`. Only this file is committed.

---

## Global constraints

Numbered so a task step can cite one. A conflict between a constraint and a step is a STOP and
report, never a judgement call.

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The cwd is
   correlated across concurrent agents (`CLAUDE.md` § Repository and direction).
2. **`set -o pipefail`** on any pipeline whose exit status you read; never `2>/dev/null` a git query
   you interpret; `git show "${ref}:path"` with braces.
3. **Stage and commit in separate Bash calls**; write the message with the Write tool and commit with
   `git commit -F <file>`.
4. **Test-modification rule (verbatim from the lead).** A test may change only when the behaviour it
   pins is the thing being changed, and every such change is listed in the PR section with its before
   and after assertion. A test that deliberately pins a defect (e2e `test.fail()` pins) is flipped to
   pin the fix, and the plan shows the flipped test failing before the fix and passing after. Never
   widen a tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a
   new test named after the defect. **The only existing tests this plan changes are six e2e
   `test.fail()` pins, each listed in its PR section.** Comment-only edits to e2e files are listed
   separately and change no assertion.
5. **Break-check every new test.** Each task names one deliberate wrong edit. Make it, run the new
   test, confirm it fails *with a message naming the mechanism* (not an import error or a side effect
   of the edit), revert, confirm green. Record the failure line in the PR description.
6. **Test container.** Hooks always use the shared container `dispatcharr-testrunner`, whose mount
   decides which tree is tested (`CLAUDE.md` § Test hooks). Re-point it at your worktree only after
   the occupancy check (`docker ps --filter name=dispatcharr-testrunner` plus file mtimes). For runs
   you launch yourself, prefer a private container:
   `DISPATCHARR_TEST_CONTAINER=fix-E-<n> DISPATCHARR_TEST_DB_VOLUME=fix-E-<n>-db CLAUDE_HOOK_REPO_ROOT=<wt> .claude/hooks/start-test-container.sh`,
   then run with the same `docker exec -w /repo -e …` environment `.claude/hooks/run-affected-tests.sh`'s
   `dexec()` uses. Run one label at a time (`manage.py test --keepdb <label>`) and **once without
   `--keepdb`** before push (the seeded-row drift trap).
7. **No category-I work.** No `test_property_*` module, no `@given`, no Hypothesis import.
8. **Ledger discipline.** Six issues here have a `metrics/curated/defects.yml` row: #7, #15, #80,
   #85, #140, #232. The PR that fixes each moves its row to `status: fixed` with `fixed_in: <this PR's
   number>` and `status_changed: <merge date>`, and validates with
   `python -m metrics.build --validate-only --curated metrics/curated`. No other issue in this plan
   has a row (checked: `grep -cE "issue: <n>[,} ]" metrics/curated/defects.yml` is `0` for the other
   fourteen). None has a parity-matrix row.
9. **Branch names** are `fix/E-<n>-<slug>`. No PR here touches `docker/`, `relay/httpapi/` or
   `docker/nginx.conf`, so none takes the `migration/` prefix.
10. **CLAUDE.md edits are anchored by exact text.** Each one quotes the sentence it replaces. If the
    quoted text is not found exactly once (an earlier plan rewrote it), STOP and report; do not
    re-derive the sentence.
11. **e2e pin flips are evidenced by CI, before and after.** Before: `main`'s latest `e2e-tests.yml`
    run shows the `test.fail()` as an expected failure. After: this PR's run shows the plain `test()`
    passing. If the PR's matrix skips the project that holds the pin, dispatch the workflow with
    `full: true`. Record both run URLs in the PR description.

---

## Files this plan touches

| file | PR |
|---|---|
| `core/migrations/0028_alter_streamprofile_parameters.py` (new) | E-1 |
| `core/scheduling.py` | E-1 |
| `core/serializers.py` | E-2 |
| `core/api_views.py` (delete `ProxySettingsViewSet`, `:206-280`, and its import) | E-2 |
| `apps/proxy/config.py` (`BaseConfig`, `:19-65`) | E-2 |
| `apps/proxy/next_source.py` (docstring of `_with_proxy_settings`, `:828-849`, only) | E-2 |
| `apps/proxy/serializers.py` (docstring of `RelayProxySettingsSerializer`, `:143-155`, only) | E-2 |
| `apps/channels/signals.py` | E-3 (`:271`, `:382`, `:385`), E-4 (`:238`) |
| `apps/channels/tasks.py` | E-3 (`:1038-1039`, `:1499`, `:2148`, `:2526`), E-9 (`:888-895`), E-4 (`:241-245`, `:345-349`, import block `:22-29`) |
| `apps/channels/api_views.py` | E-3 (`:3583-3587`), E-4 (`:877`, `:887`, `:902`, `:2074`, `:2084`, `:2099`) |
| `apps/channels/epg_matching.py` (`get_preferred_region_code`, `:428-433`) | E-4 |
| `apps/channels/serializers.py` (`:121` only) | E-6 |
| `frontend/src/utils/pages/DVRUtils.js` (`:66-68`) | E-3 |
| `frontend/src/utils/pages/__tests__/DVRUtils.test.js` (appended `it` only) | E-3 |
| `apps/m3u/tasks.py` (`refresh_m3u_groups`' nine failure returns; the caller at `:3503-3517`; the terminal write at `:3891`, `:3918`) | E-5 |
| `apps/m3u/serializers.py` (`:136` only) | E-6 |
| `apps/epg/serializers.py` (`:14`, `:201` only) | E-6 |
| `apps/output/views.py` (a helper above `:107`; `:300-306`; `:593`) | E-7 |
| `dispatcharr/urls.py` (one route after `:16`) | E-8 |
| `dispatcharr/settings.py` (`_validate_tls_cert_paths`, `:12-23`) | E-8 |
| `apps/accounts/api_views.py` (`TokenRefreshView.post`, `:133-151`) | E-8 |
| `e2e/tests/seeded/output-m3u.spec.ts`, `xc-live.spec.ts`, `m3u-refresh-failure.spec.ts`, `m3u-ingest.spec.ts`, `token-refresh-deleted-user.spec.ts`; `e2e/tests/dvr/recording-execution.spec.ts` | pin flips (E-7, E-7, E-5, E-6, E-8, E-3) |
| `e2e/COVERAGE.md`, `e2e/README.md`, other `e2e/**` comments | comment/row edits, per PR |
| `metrics/curated/defects.yml` | E-1, E-2, E-4, E-6, E-7 |
| `CLAUDE.md` | E-1, E-2, E-4, E-7 |
| new test modules, one per defect family (named in each section) | all |

## Overlap with other categories

From `sweep-report.md`, the other category issue files, and the three plans already written
(`origin/docs/fixplan-{B,J,C}`). "First" is the lead's ordering.

| file | other plan and what it is assumed to do there | who goes first | collision risk |
|---|---|---|---|
| `apps/proxy/config.py` | **J-1** deletes `HLSConfig` (`:77-88`). **J-3** adds `apps/proxy/tests/test_tune_path_query_ledger.py`, whose `_cold()` helper sets `_proxy_settings_cache = None` and `_proxy_settings_cache_time = 0` on both `BaseConfig` and `TSConfig`, and whose static pin expects `config.py`'s only model import to be `("BaseConfig.get_proxy_settings", "core.models", "CoreSettings")`. The J plan's own overlap row says E updates that test if E adds a model import or renames the attribute. | J | **None by construction.** E-2 keeps both attribute names on `BaseConfig` and adds no import (Appendix A). `_cold()` still resets the one real copy; its `TSConfig` assignment becomes an inert attribute. **E-2 changes no J-3 assertion.** One J-3 comment goes stale: `_cold()`'s docstring says CLAUDE.md records that `TSConfig`'s cache attribute shadows `BaseConfig`'s, which E-2 makes untrue. That is comment-only and is left for J-3's owner; E-2 names it in its PR description. If J-3 has not merged when E-2 runs, there is nothing to note. |
| `apps/proxy/next_source.py` | **B-5** changes `:63`; **C-4** changes `transform_url` (`:285`); **J-3** measures it. | B, C, J | Low. E-2 edits only the `_with_proxy_settings` docstring (`:828-849`). All three PRs touch a Gate 2 module, so each runs the isolated coverage script. |
| `apps/m3u/tasks.py` | **C-3** splits `refresh_m3u_groups` into an outer lock-holding function and `_refresh_m3u_groups_locked`, deleting the nine inline `lock_renewer.stop()`/`release_task_lock` pairs (C plan Appendix B). C-3 also bounds `M3UFilter` regexes for #262 (`:1026`), with no textual collision with E-5. **B-5** changes `:942-945`. **C-4** changes `:3097`. | C, B | **Real.** E-5 edits the same nine return statements C-3 edits the lines above. **E-5 is implemented after C-3 merges**, on C-3's shape: the lock-miss return lives in the outer function, the other eight in `_refresh_m3u_groups_locked`. Appendix D is written against that shape and cites seed lines. |
| `apps/output/views.py` | **B-2**: `xc_get_user` and the four XC views, lines 357-560 only, plus one import line. **C-1**: `xc_get_epg` (`:785-940`). **D #97**: `:1675-1680`. **D #94** is a decision memo; if the user rules for a `catchup=` attribute, its implementation edits the same `#EXTINF` f-string as E-7. | B, C, D | Low. E-7 adds a helper above `generate_m3u` (`:107`), edits `:300-306` and `:593` (`xc_get_live_categories`, `:564-615`), all outside B-2's range. If #94 is implemented first, E-7 rebases its f-string hunk over it and routes any new attribute through the same helper. |
| `apps/channels/signals.py` | **H #86** (the `channel-profiles.spec.ts` flake) names `create_profile_memberships` (`:235-241`) as its candidate mechanism. | E | None textually. H should re-measure #86 after E-4, which removes that mechanism. |
| `apps/channels/tasks.py` | **H #178** cites `:1234` (the DVR internal header) as evidence for an e2e-only test. | E | None. E touches no line near `:1234`. |
| `CLAUDE.md` | **B-2** rewrites the Xtream-password bullet; **J** edits the Phase 2 close-out and numeric sentences; others edit their own prose. | B, J, … | Low. E's four edits are the proxy-settings debugging trap, the scheduler-migration bullet's last clause, the preferred-region bullet and one clause of the channel-authorization bullet. Each is anchored by exact text (constraint 10). |
| `metrics/curated/defects.yml` | **B-1/B-2/B-3**, **J-1** edit other rows. | B, J | Adjacent-line rebase only. E edits six rows no other plan names. |
| `e2e/COVERAGE.md` | Every plan that flips a pin edits its own row. | — | Row-level; adjacent-line rebase only. |

No other category's evidence names `core/scheduling.py`, `core/serializers.py`, `core/api_views.py`,
`dispatcharr/settings.py`, `dispatcharr/urls.py`, `apps/accounts/api_views.py`,
`apps/channels/epg_matching.py`, `apps/{m3u,epg,channels}/serializers.py` or
`frontend/src/utils/pages/DVRUtils.js` (grepped across `issues-{A,B,C,D,F,G,H,I,J}.md`). E touches
no `core/models.py` line: the #232 receiver at `core/models.py:356-363` is correct once the cache
lives in one place, and #177's fix is a migration.

---

## Duplicates

| survivor | duplicate | basis |
|---|---|---|
| **#177** | #297 (closed by the user 2026-09-23) | Same drift: `core/models.py:57-60`'s `help_text` names `{channelId}`, and no migration records it. Same one-migration fix. |
| **#7** | #6 (closed by the user 2026-09-23) | Same line (`core/scheduling.py:121`), same mechanism. #7 carries the deterministic reproduction and the note that `CrontabSchedule` and `ClockedSchedule` share the shape. |

**Not duplicates, despite the bot:** #135 and #71. The triage bot closed #135 as a duplicate of #71.
#135 is the on-disk recording path (`apps/channels/tasks.py:1038-1039`); #71 is the frontend's
upcoming-card grouping key (`frontend/src/utils/pages/DVRUtils.js:68`). Different code, different
fix. Both are planned, in E-3.

**Tracker notes for the lead** (writes are yours, deferred): #7 and #12 still carry `wontfix`, which
the 2026-09-23 hygiene pass did not remove. #12's `wontfix` came from a bot comment calling #12 a
duplicate of itself.

---

## Per-issue analysis

Sizes: S is under 30 changed lines, M is under 150, L is more (tests excluded).
"Upstreamable" was checked against `Dispatcharr/Dispatcharr` `dev` through `gh api …/contents?ref=dev`
on 2026-09-23: every defect below is present there unless a row says otherwise, so "yes" means the
fix applies with a context rebase, since line numbers differ.

### #177 (and duplicate #297): `core.StreamProfile.parameters` has a pending migration

- **Root cause.** `core/models.py:57-60` gives `parameters` `blank=True` and a `help_text` naming
  `{channelId}`. The last migration state for the field (`core/migrations/0005`, `:24-28`) predates
  both, and no migration since mentions `channelId`.
- **Reproduced at seed.** `manage.py makemigrations --check --dry-run` over the whole project exits
  1 and lists exactly one migration, `core/migrations/0028_alter_streamprofile_parameters.py`. **No
  other app has drift.**
- **Fix.** Generate the migration. It is schema-neutral: `help_text` and `blank` never reach the
  database, so `sqlmigrate core 0028` must print no DDL. Add a project-wide `makemigrations --check`
  test so the drift cannot return silently.
- **Tests.** New `core/tests/test_no_pending_migrations.py`:
  `test_no_app_has_model_changes_without_a_migration` runs
  `call_command("makemigrations", check=True, dry_run=True, stdout=buf)`. It turns the command's
  `SystemExit` into `self.fail(buf.getvalue())`, so the failure names the app and the migration.
- **Size** S. **Upstreamable** no. Upstream `dev` already has a different
  `core/migrations/0028_alter_systemevent_event_type.py`, so this file would collide there. Note for
  a future upstream merge: the fork will then need a core merge migration.

### #7 (and duplicate #6): concurrent source creation duplicates a schedule row and 500s forever after

- **Root cause.** `core/scheduling.py:121` runs `IntervalSchedule.objects.get_or_create(every=…,
  period=HOURS)`, and `:91` runs `CrontabSchedule.objects.get_or_create(...)`. Neither
  `django_celery_beat` table has any uniqueness constraint, so two concurrent callers both miss the
  `SELECT` and both `INSERT`. Every later `get()` then raises `MultipleObjectsReturned`, which
  escapes the `M3UAccount`/`EPGSource` `post_save` receiver as a 500.
- **Reproduced at seed.** With two identical `(every=1, period=hours)` rows, a call to
  `create_or_update_periodic_task(..., interval_hours=0)` raises
  `MultipleObjectsReturned: get() returned more than one IntervalSchedule -- it returned 2!`.
- **Fix.** Add one helper, `get_or_create_schedule(model, **lookup)` (Appendix C). It returns the
  oldest matching row (`filter(**lookup).order_by("id").first()`) and creates only when none exists.
  Use it at `:91` and `:121`, and in E-3 at `apps/channels/signals.py:271` (#131). A concurrent
  insert can still add a duplicate, but a duplicate is no longer fatal. Existing duplicates need no
  data migration: the read tolerates them. A duplicate that was never chosen stays in the table,
  harmlessly. `_cleanup_orphaned_interval`/`_crontab` (`core/scheduling.py:186-203`) are not a
  sweep: they run only on a task's *old* schedule when it switches (`:112-116`). An advisory lock
  that would prevent the duplicate insert altogether is listed as a follow-up, not planned.
- **Tests.** New `core/tests/test_schedule_duplicate_rows.py`:
  - `test_duplicate_interval_rows_no_longer_break_periodic_task_creation` seeds two identical rows.
    The call must succeed, the task's `interval_id` must be the lower id, and the row count must
    stay 2.
  - `test_duplicate_crontab_rows_no_longer_break_periodic_task_creation` does the same with
    `cron_expression="0 3 * * *"` and the system time zone the call itself uses.
  - `test_get_or_create_schedule_creates_the_row_when_none_exists` is a control.
- **e2e.** `e2e/setup/bootstrap.setup.ts:102-191` pre-creates the default interval row as a harness
  mitigation. It stays: it is harmless, and removing it is harness work outside this plan.
- **Size** S. **Upstreamable** yes (upstream `dev` `core/scheduling.py:91`, `:121` identical).

### #257: the proxy-settings edit path bypasses the defaults merge

- **The issue's premise is wrong about which path is the UI's.** `core/api_views.py`'s
  `ProxySettingsViewSet` (`:206-280`), which the issue and the assessor both analyse, is **not
  routed**: `core/api_urls.py:19-23` registers `useragents`, `streamprofiles`, `outputprofiles`,
  `settings` and `notifications`, and `grep -rn ProxySettingsViewSet` finds only the definition and
  a docstring note in `apps/proxy/serializers.py:147-148` that already says it is unrouted. The
  settings page reads and writes `proxy_settings` through the generic `CoreSettingsViewSet`
  (`/api/core/settings/<id>/`, `core/api_views.py:95-143`), whose `CoreSettingsSerializer`
  (`core/serializers.py:43-92`) writes `value` verbatim.
- **The assessor's retitle ("the control loads blank") is also wrong.**
  `frontend/src/components/forms/settings/ProxySettingsForm.jsx:141-148` merges
  `getProxySettingDefaults()` under the stored value before rendering. The comment there says so:
  "Merge defaults so any newly-added keys … still show their default value rather than blank."
- **What is actually true.** (1) An older database's `proxy_settings` row still lacks
  `new_client_behind_seconds` at rest, and saving from the UI does not heal it through any server
  code path. It heals only because the frontend happens to send the merged form. (2) **The
  settings API never runs `ProxySettingsSerializer`'s range validators** (`core/serializers.py:93-140`),
  so any client can store `buffering_speed: 50` or `""`. (3) The unrouted viewset carries a third
  hardcoded copy of the defaults (`core/api_views.py:224-232`). (4) `CoreSettingsViewSet.create`
  (`frontend/src/api.js`'s `createSetting`) could still POST an unvalidated `proxy_settings` row.
  The fix below leaves create alone on purpose: `core/migrations/0014` seeds the row, so the UI only
  ever updates it, and a second row would violate `key`'s uniqueness anyway.
- **Fix (default, see open question Q1).** In `CoreSettingsSerializer.update`, when
  `instance.key == PROXY_SETTINGS_KEY`, validate `{**CoreSettings.get_proxy_settings(), **value}`
  through `ProxySettingsSerializer`, refuse a 400 on error, and store `validated_data` (Appendix B).
  A save then persists all seven keys, and an out-of-range value is refused. Delete the unrouted
  `ProxySettingsViewSet` and its import (`core/api_views.py:28`). `ProxySettingsSerializer` stays,
  now reached from the real write path. One behaviour change follows from the merge: a partial
  `value` for this group no longer drops the sibling keys. Today it does, and
  `e2e/tests/streaming-failover/failover-buffering.spec.ts:19-26` works around that with a
  read-modify-write, which keeps working.
- **Tests.** New `core/tests/test_proxy_settings_write_path.py`, through
  `/api/core/settings/<id>/` as an admin, with literal expected dicts (never a second call to
  `get_proxy_settings()`, per `ProxySettingsBackfillsMissingKeysTests`' docstring at
  `core/tests/test_core.py:840-854`):
  - `test_the_settings_page_put_stores_every_key` is the reporter's path. The UI saves with
    `PUT /api/core/settings/<id>/` and body `{key, name, value}` (`frontend/src/api.js:2433-2440`,
    `updateSetting`). The test seeds the six-key post-0026 row (every key but
    `new_client_behind_seconds`), PUTs the UI's payload with a `value` carrying the six stored keys
    and one changed, and asserts the stored row equals the literal seven-key dict. At seed the row
    has six keys.
  - `test_saving_proxy_settings_through_the_settings_api_stores_every_key` does the same through
    `PATCH`, the other verb that reaches `CoreSettingsSerializer.update`.
  - `test_out_of_range_proxy_settings_are_refused_by_the_settings_api` sends `buffering_speed: 50`,
    expects 400, and expects the row unchanged. At seed the answer is 200 and 50 is stored.
  - `test_a_partial_proxy_settings_value_keeps_its_siblings` sends `{"buffering_speed": 2.0}` and
    asserts all seven keys are stored. At seed six keys are dropped.
- **Size** M. **Upstreamable** yes (upstream `dev` `core/api_views.py:206` has the same unrouted
  viewset).

### #232: saving `proxy_settings` never clears the process-local cache readers use

- **Root cause.** `BaseConfig.get_proxy_settings` (`apps/proxy/config.py:32-65`) is a classmethod
  that writes `cls._proxy_settings_cache = settings` (`:44-45`). Reached as
  `TSConfig.get_proxy_settings()` (`apps/proxy/config_helper.py:66`, and every `TSConfig.get_*`
  getter at `config.py:130-154`), that assignment **creates** a `TSConfig` attribute at runtime,
  which shadows `BaseConfig`'s. Nothing redeclares it. `CoreSettings.invalidate_group_cache`
  (`core/models.py:347`) calls `BaseConfig.clear_proxy_settings_cache()` (`:359-361`), which resets
  only `BaseConfig`'s copy.
- **Reproduced at seed.** Read through `TSConfig` after saving `buffering_speed: 0.5`, save `9.0`,
  read again: the value is **`0.5`**. The probe had to patch `apps.proxy.config.connection`:
  `get_proxy_settings` calls `connection.close()` in its `finally` (`:60-65`), which inside a
  `TestCase` poisons the test transaction ("the connection is closed"). The new test does the same,
  and says why.
- **Impact now.** Smaller than the issue says, and CLAUDE.md overstates it. The `next-source`
  answer reads `CoreSettings.get_proxy_settings()` directly (`apps/proxy/next_source.py:827-866`),
  which is the Redis group cache, invalidated for every process by `post_save`. So **no live tune
  reads this cache**, and CLAUDE.md's "the answer is *built* from the cached values, so a threshold
  change still needs >10s to reach a new tune" is false. The cache's remaining readers are
  `ConfigHelper`'s database-backed getters (`config_helper.py:53`, `:66`, `:82`, `:127`, `:132`,
  `:137`, `:142`), and a grep finds no production caller of any of them at the seed.
- **Fix.** Keep one copy per process: `get_proxy_settings` and `clear_proxy_settings_cache` read
  and write `BaseConfig._proxy_settings_cache*` explicitly, never `cls.` (Appendix A). Attribute
  names are unchanged, so J-3 is unaffected (see overlap). Correct CLAUDE.md's debugging-trap
  paragraph and `_with_proxy_settings`' docstring, which both describe the shadow as live.
- **Tests.** New `apps/proxy/tests/test_proxy_settings_cache_invalidation.py`:
  - `test_saving_proxy_settings_clears_the_copy_tsconfig_reads` expects 0.5 then 9.0. At seed the
    second read is 0.5.
  - `test_invalidate_group_cache_clears_a_copy_read_through_any_subclass` defines
    `class _AnotherConfig(BaseConfig): pass` in the test. This pins the issue's "any future subclass
    reintroduces it" concern, not just `TSConfig`.
  - `core/tests/test_core.py:122` (`test_invalidate_clears_proxy_process_cache`, which patches
    `BaseConfig.clear_proxy_settings_cache`) stays unmodified and green.
- **Size** S. **Upstreamable** yes (upstream `dev` `apps/proxy/config.py:45` identical).

### #140: EPG regional weighting is permanently inert

- **Root cause.** Three sites read `CoreSettings.objects.get(key="preferred-region")`:
  `apps/channels/epg_matching.py:430` (`get_preferred_region_code`, `:428-433`),
  `apps/channels/tasks.py:242` (`match_epg_channels`) and `:346` (`match_selected_channels_epg`).
  `core/migrations/0020` deleted that flat row, so every read raises `DoesNotExist` and yields
  `None`. `CoreSettings.get_preferred_region()` (`core/models.py:581-582`) reads the live location,
  `system_settings["preferred_region"]`, and nothing calls it. A second latent bug: `.strip()` on a
  JSON value that is not a string would raise `AttributeError`, which the `except` does not catch.
- **Reproduced at seed.** With `system_settings.preferred_region = "uk"`,
  `CoreSettings.get_preferred_region()` returns `uk` and `get_preferred_region_code()` returns
  `None`.
- **Fix.** `get_preferred_region_code()` returns
  `CoreSettings.get_preferred_region()` lower-cased and stripped, or `None` for an empty or
  non-string value. The two task sites call it, imported through the existing
  `from apps.channels.epg_matching import (...)` block (`tasks.py:22-29`). `epg_matching.py:802`
  already calls the helper.
- **Behaviour note for the PR.** Every instance whose operator ever chose a region will start
  applying the ±15/+10 bonus (`_compute_fuzzy_score`, `epg_matching.py:211-224`) on the next match.
  That is the feature working, but it changes match results, and the description must say so.
- **Tests.** New `apps/channels/tests/test_preferred_region_is_read.py`:
  - `test_preferred_region_helper_reads_system_settings` stores `"UK"` and expects `"uk"`.
  - `test_bulk_epg_matching_passes_the_preferred_region` has one `subTest` each for
    `match_epg_channels` and `match_selected_channels_epg`. It patches
    `apps.channels.tasks.match_channels_to_epg`, `build_epg_matching_catalog` and
    `apply_matched_epg_to_channels`, and asserts `region_code == "uk"` in the call. The implementer
    confirms the full patch set against the function bodies (`tasks.py:232-330`, `:336-440`), then
    records it in the test's docstring.
  - `test_a_non_string_preferred_region_is_ignored` stores `5` and expects `None`.
  - `test_no_preferred_region_means_no_bonus` is a control.
- **Size** S. **Upstreamable** yes (upstream `dev` `epg_matching.py:430`, `tasks.py:256`, `:360`).

### #138: recurring rules materialise every day to `end_date` inside the request

- **Root cause.** `RecurringRecordingRuleSerializer.validate` requires `end_date` on create
  (`apps/channels/serializers.py:844-847`). Both REST paths call
  `sync_recurring_rule_impl(rule.id, drop_existing=True)` (`apps/channels/api_views.py:3190`,
  `:3199`). In `sync_recurring_rule_impl` (`apps/channels/tasks.py:861`),
  `if drop_existing and end_limit: end_window = end_limit` (`:890-891`) therefore always wins, and the
  14-day `horizon` branch (`:892-895`) is dead on every REST path. Every matching day's
  `Recording.objects.create` (`:940-945`) fires `schedule_task_on_save`: one `ClockedSchedule`
  `get_or_create` and one `PeriodicTask` `update_or_create` per row (`apps/channels/signals.py:271-285`).
- **Correction to the issue.** The hourly `maintain_recurring_recordings` (`tasks.py:962-971`)
  calls with `drop_existing=False`, so it **does** use the horizon. Only create and update are
  unbounded.
- **History.** The branch was added deliberately by the upstream author in `6536f35d` ("FIxed bug"),
  the same commit that made `end_date` required. That is why this was open question Q2.
- **Ruling (Q2, answered 2026-09-24).** The user rejected the default (the 14-day horizon on every
  sync) and adopted the alternative: full materialisation to `end_date` stays, `sync_recurring_rule_impl`
  is not touched, and the serializer caps `end_date`. Live streaming is the priority and DVR is
  secondary, so the fix is the smallest edit that bounds the request. This section, PR E-9, the
  coverage row and Q2 were amended on 2026-09-24 against `50b69c83`; none of the five files named
  here changed between `a54b09a9` and `50b69c83` (`git diff --stat` is empty), so the seed lines hold.
- **Measured at `50b69c83`** (private container `amend-E9`, Postgres, a throwaway probe module deleted
  afterwards). One REST create of an all-seven-days rule with `start_date` two days back, timed around
  the `POST` alone; every row also created one `ClockedSchedule` and one `PeriodicTask`:

  | `end_date` | `Recording` rows | `ClockedSchedule` / `PeriodicTask` | request |
  |---|---|---|---|
  | today+14 | 14 | 14 / 14 | 0.08 s |
  | today+30 | 30 | 30 / 30 | 0.12 s |
  | today+90 | 90 | 90 / 90 | 0.51 s |
  | today+180 | 180 | 180 / 180 | 1.20 s |
  | today+365 | 365 | 365 / 365 | 3.76 s and 5.45 s (two iterations) |
  | today+3650 | 3,650 | 3,650 / 3,650 | 104.7 s |

  The cost is superlinear: ten times the rows cost about twenty-eight times the time. The probable
  reason is the per-day `Recording.objects.filter(custom_properties__rule__id=…).exists()`
  (`tasks.py:915-919`), a JSON containment scan over a table the same loop is growing, with the
  `ClockedSchedule.objects.get_or_create(clocked_time=…)` beside it; neither was profiled and the
  plan does not depend on which. The whole five-test module below, which includes one 365-day
  create in a fresh test DB, runs in 1.8-2.0 s. Ten years is within a factor of the API process's
  120 s `harakiri` (`docker/uwsgi.ini`), so today a long enough rule kills the worker and every
  other request on it; production Postgres over a network is slower than this container.
- **Cap: 365 days from today.** One year covers a season of anything ("every weekday until next
  summer") and is the value Q2 itself offered. At the cap the request is under six seconds in the
  test DB, some twenty times inside `harakiri`, and the superlinear tail is cut before it matters
  (twice the cap would already be past 15 s on the measured curve). 90 or 180 days would be faster
  but would refuse a whole-season rule for no gain a viewer would notice. The cap is a module
  constant, `RECURRING_RULE_MAX_DAYS`, so a later change is one line, and the test that pins the
  number is its companion edit.
- **Fix.** `apps/channels/serializers.py` only (Appendix I): the constant; a helper
  `_system_local_today()` that resolves the system time zone exactly as `sync_recurring_rule_impl`
  does (`tasks.py:879-884`: `CoreSettings.get_system_time_zone()`, `ZoneInfo`, fallback to Django's
  current zone) so the cap and the walk share a calendar; and one guarded block in `validate` after
  the "End date is required" check (`:844-847`). **Only when the request itself carries `end_date`**
  (`"end_date" in attrs`) and it is later than today+365, raise a field error keyed on `end_date`:
  `End date must be no more than 365 days from today (<YYYY-MM-DD> at the latest)`. The date in the
  message is the latest accepted value, so the user sees what to enter.
  - A `PATCH` that does not carry `end_date` (the SPA's enable/disable toggle sends `{enabled}`
    alone, `frontend/src/utils/forms/RecurringRuleModalUtils.js:44-46`) is not re-capped, so a row
    created before the cap with a longer `end_date` still toggles and re-syncs as before. Deliberate:
    re-validating an untouched field would refuse a toggle with a message about a date the user did
    not enter. Such a row keeps materialising to its own `end_date` on every re-sync, unchanged from
    today; the operator shortens it through the edit modal, which sends the whole form (`:33-38`)
    and is therefore capped.
  - A `PATCH` that extends `end_date` past the cap is refused with the same message and changes
    nothing: DRF validates before `perform_update`, so no purge and no re-sync run.
  - `core.models` is already imported at module level here (`:19`, `StreamProfile`), so adding
    `CoreSettings` to that line creates no new import edge; `timedelta` and `ZoneInfo` are stdlib.
- **Tests.** New `apps/channels/tests/test_recurring_rule_end_date_cap.py` (Appendix J): five
  tests through `APIClient` as an admin, the cap pinned as the literal `365` and deliberately not
  imported from the serializer (an import turns the red run into an `ImportError`, which is not a
  red: the first prototype did exactly that and was corrected).
  - `test_a_rule_past_the_cap_is_refused_before_it_materialises_anything`: `end_date` today+366 →
    400 with the message under `end_date`; zero `RecurringRecordingRule`, zero `Recording`, zero
    `dvr-recording-*` `PeriodicTask`. **Red at seed:** `AssertionError: 201 != 400`, the body
    carrying `"end_date":"<today+366>"`.
  - `test_a_patch_that_extends_end_date_past_the_cap_is_refused_and_changes_nothing`: a 14-day rule
    is created, then `PATCH {"end_date": today+366}` → 400; `end_date` and the row count are
    unchanged. **Red at seed:** `AssertionError: 200 != 400`.
  - `test_a_rule_exactly_at_the_cap_is_accepted`: today+365 → 201 with at least 365 rows (control,
    green at seed; the one slow test, about 1.5 s).
  - `test_a_create_with_no_end_date_is_still_refused_as_required`: the existing "End date is
    required" 400 is untouched (control, green at seed).
  - `test_a_patch_that_leaves_end_date_alone_is_not_re_capped`: an ORM-created row with `end_date`
    today+395, `PATCH {"enabled": false}` → 200 and the date survives (control, green at seed;
    `enabled: false` takes the purge path, so the test materialises nothing).
  - `apps/channels/tests/test_recurring_rules.py` stays unmodified: it never goes through the
    serializer. Under rule 4 no existing test changes.
- **e2e.** `e2e/tests/dvr/recurring-rules.spec.ts` posts `end_date` = today+14, inside the cap, and
  stays green unmodified. Its "Brief vs. source" header section (`:24-91`) says the endpoint
  imposes no bound on `end_date`; that is rewritten as comment-only. `e2e/COVERAGE.md:165` moves
  from `known-bug` to `done`.
- **Frontend.** No change. Both forms already surface the serializer's message: the create form's
  `createRecurringRule` (`frontend/src/api.js:3096-3106`) and the edit modal's `updateRecurringRule`
  (`:3108-3121`) route a non-2xx through `errorNotification`, which renders a field-keyed 400 body
  as `end_date: End date must be no more than 365 days from today (…)` (`frontend/src/utils.js:120-128`)
  in a red notification before rethrowing. A `maxDate` on the two `DatePickerInput`s
  (`frontend/src/components/forms/Recording.jsx:290-298`, `RecurringRuleModal.jsx:351-356`) or a
  clause in `recurringFormValidators.end_date` (`frontend/src/utils/forms/RecordingUtils.js:174-180`)
  would state the rule a second time on a second clock, the browser's, which can disagree with the
  system time zone by a day at the boundary; the server message is the one source. If the user wants
  the picker to stop at the cap anyway, it is a `maxDate` prop on those two inputs plus one `it` in
  `frontend/src/utils/forms/__tests__/RecordingUtils.test.js` (which mocks `getNow` to 2024-06-15,
  so a validator is testable there), and it is not part of E-9.
- **Visible behaviour change.** A create or edit whose `end_date` is more than a year out gets a 400
  naming the latest accepted date. Nothing else changes: a rule within the cap materialises every
  matching day to `end_date`, exactly as `6536f35d` intended, and the Upcoming list shows its whole
  run.
- **Size** S (about 35 lines in one file). **Upstreamable** yes: upstream `dev`'s `validate` carries
  the same "End date is required" block (`serializers.py:903-906` there), so the hunk applies, and the
  fix reverses nothing of `6536f35d`.

### #132: three of the seven DVR WebSocket events carry no `recording_id`

- **Root cause.** The payloads at `apps/channels/tasks.py:1499` (`recording_started`), `:2148` and
  `:2526` (`recording_ended`), and `apps/channels/api_views.py:3583-3587` (`recording_stopped`)
  carry `channel` only. All four sites have the id in scope: `recording_id` is `run_recording`'s
  own argument (`:1399`), and `recording_id = instance.id` sits at `api_views.py:3577`. Lines
  `:2148` and `:2526` are inside `run_recording`, confirmed by indentation: the next top-level
  `def` is `recover_recordings_on_startup` at `:2552`.
- **Fix.** Add `"recording_id": recording_id` to the four payloads. The change is additive:
  `frontend/src/WebSocket.jsx:591-615` reads `data.channel` only.
- **Tests.** New `apps/channels/tests/test_dvr_ws_events_carry_recording_id.py`:
  - `test_every_recording_event_payload_carries_recording_id` is a static AST walk over every
    non-test `apps/**/*.py`. Every dict literal whose `"type"` is a string constant starting with
    `recording_` must also carry a `"recording_id"` key. At seed it fails listing exactly
    `apps/channels/tasks.py:1499`, `:2148`, `:2526` and `apps/channels/api_views.py:3585`. This is
    the only way to reach the two `recording_ended` sites without driving a full recording.
  - `test_recording_started_event_names_the_recording` is a runtime test built on
    `RunRecordingRaceGuardTests`' harness (`test_recording_stop_cancel.py:221-258`). `run_recording`
    sends `recording_started` (`:1494-1501`) before the pre-stopped check at `:1525-1531`, so the
    mocked layer's first `group_send` is the event.
  - `test_recording_stopped_event_names_the_recording` drives the stop endpoint with
    `core.utils.send_websocket_update` patched, as `StopEndpointTests` does (`:62-72`).
- **e2e.** Comments at `e2e/tests/dvr/helpers.ts:28`, `comskip.spec.ts:278` and
  `recording-execution.spec.ts:84` say these events "never" carry `recording_id`. They are updated
  as comment-only edits. No assertion changes, because the e2e correlates on `channel`, which is
  still sent.
- **Size** S. **Upstreamable** yes (upstream `dev` `tasks.py:2031`).

### #131: two recordings at an identical `start_time` can silently never be scheduled

- **Root cause.** `schedule_recording_task` runs `ClockedSchedule.objects.get_or_create(clocked_time=eta)`
  (`apps/channels/signals.py:271`). This is #7's table shape: no uniqueness, so a duplicate row makes
  every later save at that instant raise `MultipleObjectsReturned`. The `post_save` receiver's
  blanket `except` (`:383-386`) only `print()`s, so the request returns 201 with `task_id` unset.
- **Reproduced at seed.** With two `ClockedSchedule` rows at `eta`, creating a `Recording` prints
  `Error in post_save signal: get() returned more than one ClockedSchedule -- it returned 2!`, and
  `task_id` is `None`.
- **Fix.** Replace `:271` with `get_or_create_schedule(ClockedSchedule, clocked_time=eta)` from E-1.
  Replace both `print()`s (`:382`, `:385`) with `logger.exception(...)`. The module already has
  `logger` (`:16`). A `SystemEvent` is not added, because the event vocabulary
  (`apps/connect/models.py`) has no "scheduling failed" type and adding one is a product change.
- **Tests.** New `apps/channels/tests/test_recording_schedule_duplicate_clocked.py`:
  - `test_duplicate_clocked_rows_no_longer_leave_a_recording_unscheduled` expects `task_id` to be
    `dvr-recording-<id>` and the `PeriodicTask.clocked_id` to be the lower row id.
  - `test_a_recording_scheduling_failure_is_logged_at_error_not_printed` patches
    `apps.channels.signals.schedule_recording_task` to raise, then wraps the save in
    `assertLogs("apps.channels.signals", "ERROR")`.
  - `test_recording_scheduling.py` stays unmodified.
- **Size** S. **Upstreamable** yes (upstream `dev` `signals.py:305`).

### #135: an ad-hoc recording loses its channel subdirectory

- **Root cause.** `run_recording` sets `program = cp.get("program") or {}` (`tasks.py:1542`), which
  is always a dict. `_build_output_paths` (`:1024`) then computes
  `show = _safe_name(program.get('title') if isinstance(program, dict) else channel.name)`
  (`:1038`, and `title` at `:1039`), whose `else` branch can never run. `_safe_name(None)` is `""`
  (`:979-986`), and the fallback template `TV_Shows/{show}/{start}.mkv` collapses.
- **Reproduced at seed.** `_build_output_paths(channel, {}, …)` returned
  `/data/recordings/TV_Shows/20260923_210350.mkv`, with no channel segment.
- **Fix.** Fall back when the title is empty:
  `name = (program.get('title') if isinstance(program, dict) else None) or channel.name`, then
  `show = title = _safe_name(name)`.
- **Tests.** New `apps/channels/tests/test_adhoc_recording_output_path.py`:
  - `test_adhoc_recording_path_keeps_the_channel_subdirectory` asserts the path starts with
    `/data/recordings/TV_Shows/<channel name>/`.
  - `test_a_titled_programme_still_names_the_directory` is a control.
- **e2e pin flip.** `e2e/tests/dvr/recording-execution.spec.ts:368`,
  `test.fail('the recording lands where the DVR templates say it should', …)`, becomes `test(…)`.
  The assertion is unchanged (`toMatch(^/data/recordings/TV_Shows/<channelName>/\d{8}_\d{6}\.mkv$)`).
  The known-bug comment block (`:340-367`) is replaced by one line naming #135 as fixed.
- **Size** S. **Upstreamable** yes (upstream `dev` `tasks.py:1393-1394`).

### #71: every upcoming recording without EPG data collapses into one grouped card

- **Root cause.** `categorizeRecordings` builds its upcoming grouping key as
  `` `${prog.tvg_id || ''}|${(prog.title || '').toLowerCase()}` `` (`frontend/src/utils/pages/DVRUtils.js:68`).
  A recording with neither field gets `'|'`, so every such recording groups together and
  `RecordingCard.jsx` shows only the first.
- **Fix.** When the programme has neither `tvg_id` nor `title`, key on the recording itself:
  `` `rec:${rec.id ?? `${rec.channel}|${rec.start_time}`}` ``. Recurring-rule recordings carry
  `program.title` (`tasks.py:932-937`), so they still group by title as intended.
- **Tests.** Append to `frontend/src/utils/pages/__tests__/DVRUtils.test.js`, inside
  `describe('categorizeRecordings')`:
  `it('does not group upcoming recordings that have no program data (#71)')`. Two upcoming
  recordings on different channels with `custom_properties: {}` must give `upcoming` length 2, each
  with `_group_count` 1. At seed the length is 1 with count 2. The existing
  `'should handle recordings without program'` (`:457-472`) stays unmodified.
- **Not in scope.** The comment on #71 about the "Entire series + rule" action posting an empty
  `tvg_id` stays reachable only on title-grouped recurring-rule cards. It becomes a follow-up.
- **Size** S. **Upstreamable** yes (upstream `dev` `DVRUtils.js:68`).

### #72: concurrent channel and profile creation can 500 on `ChannelProfileMembership`'s `unique_together`

- **Root cause.** `create_profile_memberships` (`apps/channels/signals.py:235-241`) and
  `ChannelViewSet.create` (`apps/channels/api_views.py:853`, `bulk_create` at `:877`, `:887`,
  `:902`) each read one side of the pair and insert the cross product. `from_stream` (`:1974`,
  `:2074`, `:2084`, `:2099`) does the same. None passes `ignore_conflicts`, and
  `unique_together = ("channel_profile", "channel")` (`apps/channels/models.py:881`) turns an
  overlap into `IntegrityError`.
- **Reproduced at seed.** Re-running the receiver for a profile whose memberships exist raises
  `IntegrityError`.
- **Fix.** Pass `ignore_conflicts=True` at those seven sites. Every row they build is
  `enabled=True`, which is the field default (`models.py:876-878`), so keeping whichever row won
  loses nothing. That answers the issue's own caveat. The eighth site,
  `apps/channels/api_views.py:3165`, is deliberately left alone: it writes a caller-chosen `enabled`
  after reading the existing set, so `ignore_conflicts` there would silently drop the caller's value.
  It becomes a follow-up. `apps/m3u/tasks.py:2804` and `:2905` and `apps/channels/tasks.py:3687`
  already pass it.
- **Tests.** New `apps/channels/tests/test_profile_membership_race.py`:
  - `test_a_profile_created_concurrently_with_a_channel_does_not_raise` re-runs the receiver inside
    `transaction.atomic()` and expects exactly one row.
  - `test_channel_create_tolerates_a_membership_a_concurrent_profile_create_inserted` simulates the
    race deterministically. A temporary `post_save` receiver on `Channel` (connected in the test,
    disconnected in `addCleanup`) inserts `(P, channel)` before the view's `bulk_create`. Then
    `POST /api/channels/channels/` without `channel_profile_ids` must return 201 with exactly one
    `(P, channel)` row. A second `subTest` covers the `from-stream` route. At seed both raise
    `IntegrityError`.
- **Size** S. **Upstreamable** yes (upstream `dev` `signals.py:240`).

### #56: M3U refresh reports "download failed" when the group-refresh lock is merely held

- **Root cause.** `refresh_m3u_groups` (`apps/m3u/tasks.py:1544`) returns `(message, None)` for
  "could not run" (lock held, `:1555`; account missing or inactive, `:1565`) and for "ran and
  failed" (`:1597`, `:1610`, `:1682`, `:1721`, `:1738`, `:1750`, `:1757`). The caller
  (`:3503-3517`) treats every `None` as a download failure: it writes ERROR, sends the WebSocket
  error and returns. The create-time `refresh_m3u_groups.delay` (`apps/m3u/signals.py:12-20`) makes
  lock contention easy to hit.
- **Fix.** The two "did not run" returns gain a third element, `GROUP_REFRESH_SKIPPED` (Appendix D).
  Success still returns a 2-tuple, so `extinf_data, groups = result` (`:3519`) is untouched. The
  caller maps a skip to status IDLE, which is terminal and so is not rewritten by
  `_ensure_m3u_refresh_terminal_status` (`:143-164`). The message is "Refresh skipped: …", and no
  error notification is sent. IDLE was chosen over a Celery retry because the lock holder is the
  create-time task, whose own end state (PENDING_SETUP) is the correct one to show next. After
  C-3, the lock-miss return is in the outer function and the inactive return is in
  `_refresh_m3u_groups_locked`.
- **Tests.** In new `apps/m3u/tests/test_refresh_outcome_reporting.py` (`TransactionTestCase`, like
  `test_xc_empty_fetch_guard.py`):
  - `test_group_refresh_lock_contention_is_not_reported_as_a_download_failure` holds
    `acquire_task_lock("refresh_m3u_account_groups", id)` and runs `_refresh_single_m3u_account_impl`.
    Status must be `idle`, the message must start with `Refresh skipped`, and no
    `send_m3u_update(..., status="error")` may be sent. At seed: `error`, with the generic message.
  - `test_an_account_deactivated_mid_refresh_is_not_reported_as_a_download_failure` patches
    `apps.m3u.tasks._get_active_m3u_account` to return an in-memory active copy while the row is
    inactive, so the real `refresh_m3u_groups` takes its inactive branch.
- **Size** S. **Upstreamable** yes.

### #60: the specific refresh error is overwritten by a generic message

- **Root cause.** Every "ran and failed" return above records its specific message first, either
  inline (`:1592-1597` and its siblings) or in `fetch_m3u_lines` (every `return None, False` from
  `:178` to `:587` is preceded by `account.status = ERROR; account.last_message = error_msg; save`).
  The caller then overwrites it with "Failed to refresh M3U groups - download failed or other error"
  (`:3507-3515`).
- **Fix.** Adopt upstream's own shape. Upstream `dev` already fixed this, in
  `apps/m3u/tasks.py:3497-3524` there: when the account's current status is already ERROR, the
  caller keeps the recorded message. Otherwise it writes ERROR with `result[0]`, falling back to
  the generic text. Same hunk here (Appendix D).
- **Tests.** In the same new module:
  `test_a_recorded_fetch_failure_keeps_its_specific_message` patches
  `apps.m3u.tasks.fetch_m3u_lines` with a side effect that records
  `"M3U file not found (404) at URL: http://x"` and returns `(None, False)`. `last_message` must
  contain `404` and the status must be `error`. At seed it holds the generic text.
- **e2e pin flip.** `e2e/tests/seeded/m3u-refresh-failure.spec.ts:152`,
  `test.fail('a failed refresh keeps the HTTP-status-specific message', …)`, becomes `test(…)`, with
  its assertions (`:200-202`) unchanged. The known-bug block (`:140-151`) and the race note inside
  the body (`:180-192`) are rewritten as comment-only. The 1-second settle read stays, because it
  now proves that no late overwrite happens.
- **Size** S. **Upstreamable** yes (already fixed upstream in the same form).

### #70: a failed auto channel sync is reported as a successful refresh

- **Root cause, as the reporter's own correction states it.** `sync_auto_channels` never raises:
  its body is wrapped in a `try` whose `except` returns `{"status": "error", …}`. The caller renders
  that as `" Auto-sync error: …"` (`apps/m3u/tasks.py:3869-3872`), then sets
  `Status.SUCCESS` unconditionally (`:3891`) and sends `status="success"` (`:3918`).
- **Fix.** Track `auto_sync_failed`. It is true when the result's `status` is `"error"`, or when the
  caller's own `except` (`:3873-3876`) fires, which now also appends an `Auto-sync error:` segment.
  When it is true, the terminal write sets `Status.ERROR`, keeps the same `last_message`, and sends
  the final update with `status="error"` and `error=last_message`. `updated_at` still advances,
  because the stream refresh itself succeeded and `updated_at` documents "last successfully
  refreshed". The `" Auto-sync: N failed."` shape from `RANGE_EXHAUSTED` is out of scope and becomes
  a follow-up.
- **Tests.** In the same new module:
  `test_a_failed_auto_sync_is_not_reported_as_success` reuses
  `test_non_empty_xc_fetch_still_runs_sync`'s harness (`test_xc_empty_fetch_guard.py:98-135`) with
  `sync_auto_channels` returning `{"status": "error", "error": "boom"}`. The status must be `error`,
  `last_message` must contain `Auto-sync error: boom`, and the last `send_m3u_update` must carry
  `status="error"`. At seed the status is `success`. `test_xc_empty_fetch_guard.py:131`, which
  asserts SUCCESS for an `ok` sync, stays unmodified and green.
- **Size** S. **Upstreamable** yes (upstream `dev` `tasks.py:3912`).

### #15: `read_only_fields` in the serializer class body, where DRF never reads it

- **Root cause.** `apps/m3u/serializers.py:136` (`M3UAccountSerializer`), `apps/epg/serializers.py:14`
  (`EPGSourceSerializer`) and `:201` (`EPGDataSerializer`), and `apps/channels/serializers.py:121`
  (`StreamSerializer`) all assign `read_only_fields` at class-body indentation, above `class Meta`.
- **Reproduced at seed.** A partial `M3UAccountSerializer` save with `locked: true`,
  `updated_at: 1999-01-02T03:04:05Z` persisted both.
- **Fix.** Move each list into its `Meta`. Checked consequences:
  - `EPGDataViewSet` is a `ReadOnlyModelViewSet` (`apps/epg/api_views.py:728`), so that one changes
    nothing.
  - For `StreamSerializer`, a custom stream's `m3u_account` and `is_custom` are set by the
    `pre_save` receiver `set_default_m3u_account` (`apps/channels/signals.py:52-65`), not by the
    client, and `stream_hash` by `generate_custom_stream_hash` (`:67-79`). The frontend only *reads*
    `is_custom`, `stream_hash` and `stream_chno` (`StreamsTable.jsx:124`, `:181`,
    `ChannelTableStreams.jsx:235`).
  - Nothing writes `locked` or `updated_at` through a serializer. The refresh task uses the ORM.
- **Tests.**
  - `apps/m3u/tests/test_serializer_read_only_fields.py`:
    `test_m3u_account_locked_and_updated_at_are_not_writable_over_the_api` PATCHes and re-reads.
  - `apps/epg/tests/test_serializer_read_only_fields.py`:
    `test_epg_source_updated_at_is_not_writable_over_the_api`, plus
    `test_epg_data_epg_source_is_read_only` at field level.
  - `apps/channels/tests/test_stream_serializer_read_only_fields.py`:
    `test_stream_system_fields_are_read_only` at field level, over the five names, plus
    `test_creating_a_custom_stream_still_works` as a control (POST → 201, `is_custom` true).
  - `tests/test_no_class_body_read_only_fields.py`: `test_no_serializer_declares_read_only_fields_outside_meta`
    is an AST scan over every non-test `apps/**/serializers.py` and `core/serializers.py`. It fails
    naming `file:line` for any class-body assignment. The issue notes that neither DRF nor any
    linter here warns about this.
- **e2e pin flip.** `e2e/tests/seeded/m3u-ingest.spec.ts:356`,
  `test.fail('M3UAccount.locked is not writable over the API', …)`, becomes `test(…)`, with its
  assertions unchanged. The known-bug block (`:338-355`) is replaced by one line. The
  `e2e/fixtures/types.ts:692-698` and `:774-777` comments lose their "#15" clause, as comment-only
  edits. Those types already exclude the fields.
- **Size** S. **Upstreamable** yes (upstream `dev` `apps/m3u/serializers.py:136`).

### #80: an unescaped double quote in `tvg-name`/`group-title` breaks the `#EXTINF` line

- **Root cause.** `generate_m3u` interpolates `tvg_id`, `tvg_name`, `tvg_logo`,
  `formatted_channel_number`, `effective_tvc_guide` (`:298-301`) and `group_title` into
  double-quoted attributes with no escaping (`apps/output/views.py:304-306`). The values come from
  `:269-296`.
- **Fix (default, Q3).** A helper, `_m3u_attr(value)`, returns `str(value).replace('"', "&quot;")`
  and is applied to every quoted attribute value. It sits above `generate_m3u` (`:107`), outside
  B-2's range. The display name after the comma stays raw, because it runs to end of line. `&` is
  left alone on purpose: common IPTV players, and Dispatcharr's own importer
  (`apps/m3u/tasks.py:166`, `:598-630`, which never unescapes), read M3U attributes literally, so
  `html.escape` would show every "AT&T" as `AT&amp;T`. The e2e pin's two assertions (`wellFormed`,
  and entity-decoded round trip) are both satisfied.
- **Tests.** New `apps/output/tests/test_m3u_attribute_quoting.py`, built on `OutputM3UTest`'s
  harness (`apps/output/tests/test_views.py:94-141`):
  - `test_double_quote_in_channel_name_does_not_break_extinf` parses the emitted line with
    `apps.m3u.tasks.parse_extinf_line`. `tvg-name` and `group-title` must equal the
    `&quot;`-escaped values, the display name must equal the raw name, and the attribute keys must
    be exactly the expected set, with nothing spilled.
  - `test_ampersand_in_channel_name_is_left_alone` is a control.
- **e2e pin flip.** `e2e/tests/seeded/output-m3u.spec.ts:194`, `test.fail('a channel name containing
  a double quote still produces a well-formed EXTINF line (#80)', …)`, becomes `test(…)`, with its
  assertions (`:219-225`) unchanged. The comment block (`:146-192`) is rewritten to state the chosen
  escaping. `e2e/tests/seeded/parse-fixture.spec.ts:51-54` comment is updated.
- **Size** S. **Upstreamable** yes (upstream `dev` `views.py:378`).

### #85: `xc_get_live_categories` filters `user_level` exactly for profiled users

- **Root cause.** `apps/output/views.py:593` is `"channels__user_level": 0`. The no-profile branch
  (`:586`), the admin branch (`:601`) and `_xc_live_streams_setup` all use
  `__lte=user.user_level`. `grep` finds no other exact `user_level` filter outside tests and
  migrations (`apps/m3u/tasks.py:2750` is an object creation, not a filter).
- **Fix.** `"channels__user_level__lte": user.user_level`.
- **Tests.** New `apps/output/tests/test_xc_live_categories_user_level.py`:
  - `test_profiled_user_sees_the_category_of_every_channel_it_can_list` uses a level-1 user with a
    profile and a level-1 channel in group G with an enabled membership, and expects G. At seed it
    is missing.
  - `test_profiled_user_does_not_see_a_category_above_its_level` is a control, with a level-2
    channel.
- **e2e pin flip.** `e2e/tests/seeded/xc-live.spec.ts:215`,
  `test.fail('a profiled user sees the category of every channel it can list', …)`, becomes
  `test(…)`, with its assertions unchanged. The comment at `:199-214` becomes one line.
- **Size** S. **Upstreamable** yes (upstream `dev` `views.py:662`).

### #57: an unmatched `/api/` path answers 200 with `index.html`

- **Root cause.** `dispatcharr/urls.py:16` includes `apps.api.urls`. When that include cannot
  resolve the remainder, resolution continues to the SPA catch-alls (`:97-98`). No `handler404` or
  `/api/` fallback exists.
- **Reproduced at seed.** `resolve("/api/does-not-exist/")` and
  `resolve("/api/channels/does-not-exist/")` both give `TemplateView`.
- **Fix.** Right after `:16`, add `re_path(r"^api/", api_not_found)`. `api_not_found` is a
  `csrf_exempt` function in `dispatcharr/urls.py` answering
  `JsonResponse({"detail": "Not found."}, status=404)` for every method (Appendix E).
  `authorize_views._surface_for` resolves `X-Original-URI` through Django's resolver and keys on the
  view's `__name__`. An unmatched `/api/` URI resolved to `TemplateView` before and resolves to
  `api_not_found` now. Neither is a streaming surface, so the authorize answer (403) is unchanged.
  `apps.proxy.tests` runs on this PR anyway.
- **Behaviour change.** `apps/api/urls.py` has no root pattern, so `/api/` itself (and `/api`, via
  the redirect at `dispatcharr/urls.py:17`) answers the SPA shell with 200 today and will answer the
  JSON 404 after the fix. That is correct, and the PR description says so.
- **Tests.** New `tests/test_unmatched_api_paths_404.py`:
  - `test_unmatched_api_paths_resolve_to_a_404_not_the_spa` is resolver-level and red at seed.
  - `test_unmatched_api_path_answers_json_404` uses the test client.
  - `test_spa_routes_and_real_api_routes_are_unchanged` is a control: `/channels` still resolves to
    `TemplateView`, and `/api/channels/channels/` still resolves to its viewset.
  - `e2e/tests/seeded/api-fixture.spec.ts:8-19` names the SPA fallthrough only as a hazard it
    guards against, and it stays unmodified.
- **Size** S. **Upstreamable** yes (upstream `dev` `urls.py:73`).

### #128: an unreadable TLS certificate raises a raw `PermissionError`

- **Root cause.** `_validate_tls_cert_paths` (`dispatcharr/settings.py:12-23`) calls
  `Path(file_path).is_file()` bare (`:19`). On Python 3.13, the production image's version
  (`docker/DispatcharrBase:36`), `is_file()` re-raises `EACCES` from `os.stat`. The call sites are
  `:64` (Redis) and `:287` (PostgreSQL).
- **Fix.** Catch `OSError` around `is_file()` and raise `ImproperlyConfigured` naming the variable,
  the path and `exc.strerror`, with a "check that the application user can traverse the directory
  and read the file" hint. The existing "file not found" branch is unchanged (Appendix F).
- **Tests.** New `tests/test_tls_cert_path_validation.py`:
  - `test_unreadable_cert_path_raises_improperly_configured_not_permission_error` patches
    `pathlib.Path.is_file` with `side_effect=PermissionError(13, "Permission denied")`. A real
    `chmod 000` cannot be used, because the test container runs as root. At seed the test ERRORs
    with `PermissionError`.
  - `test_missing_cert_path_still_says_file_not_found` is a control.
- **Size** S. **Upstreamable** yes (upstream `dev` `settings.py:19`).

### #12: token refresh 500s when the refresh token names a deleted user

- **Root cause.** simplejwt 5.5.1 (`uv.lock:789-790`) `TokenRefreshSerializer.validate` does a bare
  `get_user_model().objects.get(...)`. `apps/accounts/api_views.py:133-151` passes straight to
  `super().post`, so `User.DoesNotExist` escapes as a 500.
- **Reproduced at seed.** The probe's `POST /api/accounts/token/refresh/` with a deleted user's
  token raised `DoesNotExist`.
- **Fix.** Wrap `super().post` in `try/except User.DoesNotExist: raise InvalidToken()`
  (Appendix G). DRF then answers 401 with `code: "token_not_valid"`, the shape every other invalid
  refresh already gets. The fix does not depend on the simplejwt version.
- **Tests.** New `apps/accounts/tests/test_token_refresh_deleted_user.py`:
  - `test_refreshing_a_deleted_users_token_is_401_not_500` issues `RefreshToken.for_user(u)`,
    deletes `u`, POSTs, and expects 401 with `code == "token_not_valid"`.
  - `test_refreshing_a_live_users_token_still_works` is a control.
- **e2e pin flip.** `e2e/tests/seeded/token-refresh-deleted-user.spec.ts:69`,
  `test.fail('refreshing a deleted user\'s token returns 401, not 500', …)`, becomes `test(…)`, with
  its assertions unchanged. The login-throttle note in its comment stays, because it is still true.
  Comment-only edits: `e2e/README.md:470` paragraph, `e2e/setup/login.ts:115`,
  `e2e/setup/principals.ts:296` and `e2e/fixtures/auth.ts:153`.
- **Size** S. **Upstreamable** yes (upstream `dev` `api_views.py:151`).

---

## PR sections, in implementation order

Every PR: branch off the current `main`, run the named labels in a private container
(constraint 6), run once without `--keepdb`, and open as a **draft**. The only existing tests
changed are the e2e pins each section lists.

### PR E-1: `fix/E-1-core-schedules-and-migration`

- **Closes** #177 (with #297) and #7 (with #6).
- **Files** `core/migrations/0028_alter_streamprofile_parameters.py` (new), `core/scheduling.py`,
  `metrics/curated/defects.yml`, `CLAUDE.md`, `core/tests/test_no_pending_migrations.py` (new),
  `core/tests/test_schedule_duplicate_rows.py` (new).
- **Labels** `core.tests`.
- **Tasks.**
  1. Write `test_no_pending_migrations.py`. Run it. It must fail, naming
     `core/migrations/0028_alter_streamprofile_parameters.py`.
  2. Generate the migration on the host: `uv run python manage.py makemigrations core --name
     alter_streamprofile_parameters`. The container mount is read-only, so if the host cannot run
     it, use `-v 3 --dry-run` in the container and write the printed file. The file must contain
     one `AlterField` for `parameters`, with `blank=True` and the model's `help_text` verbatim.
     `manage.py sqlmigrate core 0028` must print no DDL. Green.
     **Break-check:** move the migration file out of the tree, and the test must redden naming
     `core` and `0028_alter_streamprofile_parameters`.
  3. Write `test_schedule_duplicate_rows.py`. At seed the two duplicate tests must ERROR with
     `MultipleObjectsReturned`.
  4. Add `get_or_create_schedule` and use it at `:91` and `:121` (Appendix C). Green.
     **Break-check:** restore the bare `get_or_create` at `:121` only. The interval test alone must
     redden with `get() returned more than one IntervalSchedule`.
  5. Ledger: the `interval-schedule-create-race` row (`defects.yml:24`) becomes fixed
     (constraint 8). Validate.
  6. CLAUDE.md (constraint 10). Replace
     "16 migrations have no reverse; nothing in CI exercises reverse migrations or `makemigrations --check`."
     with
     "16 migrations have no reverse; nothing in CI exercises reverse migrations, and `makemigrations --check` runs only as `core/tests/test_no_pending_migrations.py`, which is to say only when the `core.tests` label runs (#177)."
  7. Run `core.tests` whole, then once without `--keepdb`.
- **Note.** C's open question C-Q3 asks whether migration paths should route to more labels. The
  same answer would decide whether this test should run on every PR that adds a migration. That is
  not decided here.
- **Upstreamable** partly. The scheduling hunk is yes. The migration is no (upstream `dev` has its
  own core `0028`).
- **PR description draft.**

  > **fix(core): tolerate duplicate beat schedule rows, and add the missing StreamProfile migration (#7, #177)**
  >
  > `django_celery_beat`'s schedule tables have no uniqueness, so two concurrent M3U/EPG source
  > creates could insert a duplicate `IntervalSchedule` and every later create 500'd with
  > `MultipleObjectsReturned`, permanently. Schedule lookups now take the oldest matching row and
  > create only when none exists (`core.scheduling.get_or_create_schedule`, also used for cron
  > schedules and, in a follow-up PR, DVR clocked schedules). `core/0028` records the
  > `StreamProfile.parameters` help text and `blank=True` the model has carried since Alpha v3; it
  > is schema-neutral (`sqlmigrate` prints no DDL), and a new test runs `makemigrations --check` for
  > every app. Closes #7 (dup #6), #177 (dup #297). Break-checks: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-2: `fix/E-2-proxy-settings`

- **Closes** #232 and #257.
- **Waits for** J-1 and J-3 to merge (both touch `apps/proxy/config.py`). If J-3 has merged, confirm
  that `test_tune_path_query_ledger.py` passes **unmodified**.
- **Files** `apps/proxy/config.py`, `apps/proxy/next_source.py` (docstring),
  `apps/proxy/serializers.py` (docstring), `core/serializers.py`, `core/api_views.py`,
  `metrics/curated/defects.yml`, `CLAUDE.md`,
  `apps/proxy/tests/test_proxy_settings_cache_invalidation.py` (new),
  `core/tests/test_proxy_settings_write_path.py` (new).
- **Labels** `apps.proxy.tests`, `core.tests`. **Gate 2:** `next_source.py` is a Gate 2 module.
  The edit is docstring-only, but run `scripts/coverage_live_path_isolated.sh --gate` before push
  anyway (the standing rule for any coveragerc-listed module).
- **Tasks.**
  1. #232: write `test_proxy_settings_cache_invalidation.py`, with `apps.proxy.config.connection`
     patched and the reason in the class docstring. At seed the first test must fail `0.5 != 9.0`.
  2. Apply Appendix A. Green.
     **Break-check:** restore `cls._proxy_settings_cache = settings` at `:44`. The first test must
     redden `0.5 != 9.0`.
  3. Re-verify that the cache has no production reader:
     `grep -rnE "new_client_behind_seconds\(\)|channel_shutdown_delay\(\)|redis_chunk_ttl\(\)|buffering_timeout\(\)|buffering_speed\(\)|channel_init_grace_period\(\)|channel_client_wait_period\(\)|get_proxy_settings\(\)" --include='*.py' apps core | grep -v /tests/`.
     Run it before applying Appendix A. At the seed it prints exactly these lines:
     `apps/proxy/config_helper.py:51`, `:53`, `:61`, `:66`, `:80`, `:82`, `:125`, `:127`, `:130`,
     `:132`, `:135`, `:137`, `:140`, `:142`; `apps/proxy/config.py:43`, `:70`, `:75`, `:130`,
     `:136`, `:142`, `:148`, `:154`, `:160`, `:164`, `:168`, `:172`, `:176`;
     `apps/proxy/next_source.py:860` (the `CoreSettings` call that bypasses the cache); and two
     docstring lines, `apps/proxy/serializers.py:137` and `:153`. Line numbers may drift after J-1;
     the files may not. **STOP only on a new call site**: a non-docstring line in any other file.
     That would falsify the CLAUDE.md text in step 7.
  4. #257: write `test_proxy_settings_write_path.py`. At seed the four tests must fail: six keys
     stored (PUT and PATCH); 200 not 400; siblings dropped.
  5. Apply Appendix B. Delete `ProxySettingsViewSet` (`core/api_views.py:206-280`) and its
     `ProxySettingsSerializer` import (`:28`). Green.
     **Break-checks:** (a) validate `value` alone instead of the merged dict, and the partial-value
     test must redden with a 400 naming a required field; (b) drop the `is_valid()` refusal, and the
     out-of-range test must redden `200 != 400`.
  6. Docstrings. In `next_source.py:833-839`, replace the sentences describing the shadow with: "That
     cache is also not in the path for a better reason than staleness: this answer must reflect a
     save at once, and CoreSettings' Redis group cache is invalidated for every process by post_save."
     In `apps/proxy/serializers.py:146-155`, the clause "It was latent only because
     core.serializers.ProxySettingsSerializer's own viewset (core/api_views.py's
     ProxySettingsViewSet) is unrouted; the day someone routes it, …" becomes "It is latent because
     core.serializers.ProxySettingsSerializer is never a schema component: since #257 it validates
     imperatively inside CoreSettingsSerializer.update. If it is ever declared as a field, …". The
     rest of the paragraph is unchanged.
  7. CLAUDE.md (constraint 10). In § Known defects and traps, "Two debugging traps.", replace the
     sentences from "**`proxy_settings` is cached process-locally for 10s across four uWSGI
     workers**" through "…and still must land before the channel starts." with Appendix A's
     replacement text.
  8. Ledger: the `proxy-settings-cache-cleared-on-wrong-class` row (`defects.yml:33`) becomes fixed.
     Validate.
  9. Run `apps.proxy.tests` and `core.tests` whole, then once without `--keepdb`. Run the isolated
     Gate 2 script.
- **Behaviour changes to state in the PR.** A proxy-settings save from any client is now validated.
  The UI's own ranges (`ProxySettingsForm.jsx:35-41`) are looser than the serializer's
  (`redis_chunk_ttl` has a minimum of 10, `buffering_speed` a minimum of 0.1), so a UI save outside
  them now gets a 400 where it used to be stored. A partial `value` keeps its siblings.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(proxy,core): one proxy-settings cache per process, and validate proxy-settings writes on the path the UI actually uses (#232, #257)**
  >
  > `BaseConfig.get_proxy_settings()` stored its cache with `cls.`, so every read through
  > `TSConfig` created a shadowing attribute the save-time invalidation never cleared; it now reads
  > and writes `BaseConfig`'s copy explicitly, whatever subclass it is reached through. (No live
  > tune reads that cache — the next-source answer uses the Redis group cache — so CLAUDE.md's claim
  > that a threshold change needs >10s to reach a new tune is corrected.) #257 analysed
  > `ProxySettingsViewSet`, which was never routed; the settings page writes through
  > `/api/core/settings/<id>/`, which stored `proxy_settings` verbatim with no validation. That path
  > now validates the effective value through `ProxySettingsSerializer` and stores all seven keys;
  > the unrouted viewset and its third copy of the defaults are deleted. (J-3's `_cold()` docstring
  > still describes the shadow; its assertions are unaffected.) Closes #232, #257.
  > Break-checks: <paste>. No existing test changed. Gate 2: <paste --gate line>.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-3: `fix/E-3-dvr`

- **Closes** #131, #132, #135 and #71. (#138 moved to E-9 in review round 1.)
- **Waits for** E-1 (`get_or_create_schedule`).
- **Files** `apps/channels/signals.py`, `apps/channels/tasks.py`, `apps/channels/api_views.py`,
  `frontend/src/utils/pages/DVRUtils.js`, `frontend/src/utils/pages/__tests__/DVRUtils.test.js`
  (appended `it` only), `e2e/tests/dvr/recording-execution.spec.ts` (pin flip), comment-only edits to
  `e2e/tests/dvr/{helpers.ts,comskip.spec.ts}` and
  `e2e/tests/frontend/dvr.spec.ts`, `e2e/COVERAGE.md`, three new backend test modules
  (`test_recording_schedule_duplicate_clocked.py`, `test_dvr_ws_events_carry_recording_id.py`,
  `test_adhoc_recording_output_path.py`); #71's test is a vitest append.
- **Labels** `apps.channels.tests`, plus the frontend suite
  (`cd frontend && npx vitest --run src/utils/pages/__tests__/DVRUtils.test.js`, then `npm test`).
- **Tasks.**
  1. #131: write `test_recording_schedule_duplicate_clocked.py`. At seed the first test must fail
     `None != 'dvr-recording-<id>'`, and the second must fail with "no logs of level ERROR".
  2. `signals.py:271` becomes `get_or_create_schedule(ClockedSchedule, clocked_time=eta)` (import
     from `core.scheduling`). `:382` becomes `logger.warning(...)` and `:385-386` becomes
     `logger.exception(...)`. Green.
     **Break-check:** restore `:271`. The first test must redden, and the ERROR log must now name
     `MultipleObjectsReturned`.
  3. #132: write `test_dvr_ws_events_carry_recording_id.py`. At seed the static test must list the
     four `file:line`s, and both runtime tests must fail on a missing key.
  4. Add `recording_id` to the four payloads. Green.
     **Break-check:** remove it from `tasks.py:2526` only. The static test alone must redden, naming
     that line.
  5. #135: write `test_adhoc_recording_output_path.py`. At seed it fails on
     `/data/recordings/TV_Shows/<start>.mkv`. Apply the fix. Green.
     **Break-check:** restore `:1038`. The test must redden.
  6. #71: append the vitest case. At seed it fails with length 1 against 2. Apply the fix. Green.
     **Break-check:** restore the key. It must redden.
  7. e2e: flip `recording-execution.spec.ts:368` (constraint 11), replace its known-bug comment
     block, and make the comment-only edits listed under #132 and #71.
     `grep -rnE "#(131|132|135|71)\b" e2e/` and update any sentence that describes a defect
     here as present. Change no assertion except the flip.
  8. `e2e/COVERAGE.md`: the DVR rows for #135 (`:156`), #131 (`:163`) and #132 (`:164`) record
     the fix and point at the new backend tests.
  9. Run `apps.channels.tests` whole, then once without `--keepdb`, then `npm test` in `frontend/`.
- **Pin flip, before and after.**

  | test | before | after |
  |---|---|---|
  | `recording-execution.spec.ts` `'the recording lands where the DVR templates say it should'` | `test.fail(...)`; final `toMatch(^/data/recordings/TV_Shows/<channelName>/\d{8}_\d{6}\.mkv$)` fails on `/data/recordings/TV_Shows/<start>.mkv` | `test(...)`; same assertion, passes |

- **Upstreamable** yes.
- **PR description draft.**

  > **fix(dvr): schedule recordings that share a start time, name the recording in every WS event, keep the channel directory for ad-hoc recordings, and stop grouping EPG-less upcoming cards (#131, #132, #135, #71)**
  >
  > A duplicate `ClockedSchedule` row left every later recording at that instant silently
  > unscheduled (201, no task, a `print()`); lookups now tolerate it and failures log at ERROR.
  > `recording_started`, `recording_stopped` and both `recording_ended` payloads carry
  > `recording_id`. An ad-hoc recording's `{show}` falls back to the channel name, as the dead
  > `else` branch intended. Upcoming recordings with no programme data no longer collapse into one
  > "Next of N" card. Closes #131, #132, #135, #71. Break-checks: <paste>. e2e: the #135 pin is
  > flipped (before <run URL>, after <run URL>).
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-4: `fix/E-4-epg-region-and-memberships`

- **Closes** #140 and #72.
- **Files** `apps/channels/epg_matching.py`, `apps/channels/tasks.py`, `apps/channels/signals.py`,
  `apps/channels/api_views.py`, `metrics/curated/defects.yml`, `CLAUDE.md`, `e2e/COVERAGE.md`,
  comment-only `e2e/tests/seeded/channel-bulk-ops.spec.ts:17`, two new test modules.
- **Labels** `apps.channels.tests`.
- **Tasks.**
  1. #140: write `test_preferred_region_is_read.py`. At seed the helper test must fail
     `None != 'uk'`.
  2. Rewrite `get_preferred_region_code` and replace the two task sites. Green.
     **Break-check:** restore the inline lookup at `tasks.py:345-349` only. The
     `match_selected_channels_epg` subTest alone must redden with `None != 'uk'`.
  3. #72: write `test_profile_membership_race.py`. At seed both tests must raise `IntegrityError`
     (duplicate key on the `channel_profile_id, channel_id` constraint).
  4. Add `ignore_conflicts=True` at the seven sites. Leave `:3165`. Green.
     **Break-check:** drop it at `api_views.py:877` only. The channel-create subTest alone must
     redden with `IntegrityError`.
  5. Ledger: the `preferred-region-dead-read` row (`defects.yml:12`) becomes fixed. Validate.
  6. CLAUDE.md (constraint 10): delete the whole bullet beginning "- The `preferred-region` read can
     never succeed".
  7. `e2e/COVERAGE.md`: the rows for #140 (`:182`) and #72 (`:191`) record the fix.
  8. Run `apps.channels.tests` whole, then once without `--keepdb`.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(channels): read the preferred EPG region from where it lives, and make profile-membership inserts conflict-tolerant (#140, #72)**
  >
  > All three preferred-region reads looked up a `CoreSettings` row `core/0020` deleted, so EPG
  > matching never applied its region bonus. They now read `system_settings.preferred_region`.
  > **Instances with a region set will see match results change on the next EPG match** — that is
  > the setting starting to work. Channel creation and profile creation populate
  > `ChannelProfileMembership` from opposite sides; run together they could insert the same pair and
  > 500. The seven all-profiles/all-channels inserts now ignore conflicts (every row they write is the
  > field default, `enabled=True`); the profile bulk-edit insert, which writes a caller-chosen value,
  > is deliberately unchanged. Closes #140, #72. Break-checks: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-5: `fix/E-5-m3u-refresh-outcomes`

- **Closes** #56, #60 and #70.
- **Waits for** C-3 to merge (constraint in the overlap table). Rebase onto C-3's
  `refresh_m3u_groups` / `_refresh_m3u_groups_locked` split before editing.
- **Files** `apps/m3u/tasks.py`, `e2e/tests/seeded/m3u-refresh-failure.spec.ts` (pin flip),
  comment-only `e2e/tests/seeded/auto-channel-sync.spec.ts:119-150`, `e2e/COVERAGE.md`,
  `apps/m3u/tests/test_refresh_outcome_reporting.py` (new).
- **Labels** `apps.m3u.tests`.
- **Tasks.**
  1. Write the module's five tests. At seed the three reporting tests show `error` plus the generic
     message, and the #70 test shows `success`.
  2. Apply Appendix D: the constant, the two skip returns, the caller's three branches and the
     terminal write. Green.
     **Break-checks:** (a) drop the `GROUP_REFRESH_SKIPPED` branch in the caller, and the contention
     test must redden with `'error' != 'idle'`; (b) drop the "already ERROR" guard, and the #60 test
     must redden with the generic message; (c) make the terminal status unconditional again, and the
     #70 test must redden with `'success' != 'error'`.
  3. Confirm that `test_xc_empty_fetch_guard.py`, `test_memory_cleanup.py` (which mock
     `refresh_m3u_groups` with 2-tuples), `test_refresh_db_recovery.py` and C-3's
     `test_non_utf8_playlist.py` pass **unmodified**.
  4. e2e: flip `m3u-refresh-failure.spec.ts:152` (constraint 11). Make the comment-only rewrites
     listed under #60 and #70.
  5. `e2e/COVERAGE.md`: the #60 row (`:37`) records the fix.
  6. Run `apps.m3u.tests` whole, then once without `--keepdb`.
- **Pin flip, before and after.**

  | test | before | after |
  |---|---|---|
  | `m3u-refresh-failure.spec.ts` `'a failed refresh keeps the HTTP-status-specific message'` | `test.fail(...)`; `expect(settled.last_message).toContain('404')` fails on the generic text | `test(...)`; same three assertions, pass |

- **Upstreamable** yes (the #60 hunk mirrors upstream `dev`).
- **PR description draft.**

  > **fix(m3u): tell "did not run" from "failed", keep the recorded failure message, and do not report a failed auto-sync as success (#56, #60, #70)**
  >
  > `refresh_m3u_groups` returned `(message, None)` for lock contention and for a missing or
  > inactive account as well as for a real failure, and the caller wrote "download failed or other
  > error" over all of them. The two did-not-run cases now carry `GROUP_REFRESH_SKIPPED` and end at
  > IDLE with "Refresh skipped: …" and no error notification; a real failure keeps the specific
  > message the failing step already recorded (the same shape upstream `dev` adopted). A refresh
  > whose auto channel sync returned an error now ends at ERROR, with the same summary message.
  > Closes #56, #60, #70. Break-checks: <paste>. e2e: the #60 pin is flipped (before <run URL>,
  > after <run URL>).
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-6: `fix/E-6-serializer-read-only-fields`

- **Closes** #15.
- **Files** `apps/m3u/serializers.py`, `apps/epg/serializers.py`, `apps/channels/serializers.py`,
  `metrics/curated/defects.yml`, `e2e/tests/seeded/m3u-ingest.spec.ts` (pin flip), comment-only
  `e2e/fixtures/types.ts`, `e2e/COVERAGE.md`, four new test modules.
- **Labels** `apps.m3u.tests`, `apps.epg.tests`, `apps.channels.tests`, `tests`. There are four
  because one defect spans three apps' serializers, and the guard scans them all. Splitting would
  split one issue.
- **Tasks.**
  1. Write the four test modules. At seed the three per-app writes persist, the field-level
     assertions fail, and the AST scan lists the four `file:line`s.
  2. Move each list into its `Meta`. Green.
     **Break-check:** move `EPGSourceSerializer`'s list back to the class body. The EPG test and
     the AST scan must both redden, the scan naming `apps/epg/serializers.py:14`.
  3. e2e: flip `m3u-ingest.spec.ts:356` (constraint 11). Make the `types.ts` comment-only edits.
  4. Ledger: the `read-only-fields-misplaced` row (`defects.yml:23`) becomes fixed. Validate.
     `e2e/COVERAGE.md` row `:36` records the fix.
  5. Run the four labels, then once without `--keepdb`.
- **Pin flip, before and after.**

  | test | before | after |
  |---|---|---|
  | `m3u-ingest.spec.ts` `'M3UAccount.locked is not writable over the API'` | `test.fail(...)`; `expect(readBack.locked).toBe(false)` fails on `true` | `test(...)`; same assertions, pass |

- **Upstreamable** yes.
- **PR description draft.**

  > **fix(serializers): put read_only_fields in Meta where DRF reads it (#15)**
  >
  > Four serializers declared `read_only_fields` in the class body, where DRF ignores it: an API
  > client could set `M3UAccount.locked` and forge `updated_at` ("last successful refresh") on M3U
  > accounts and EPG sources. Each list moves into `Meta`; a new guard fails on any serializer that
  > repeats the mistake. Custom-stream creation is unaffected (its `m3u_account`/`is_custom` are set
  > by the `pre_save` receiver, never by the client). Closes #15. Break-checks: <paste>. e2e: the #15
  > pin is flipped (before <run URL>, after <run URL>).
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-7: `fix/E-7-output-m3u-and-xc-categories`

- **Closes** #80 and #85.
- **Waits for** B-2 and C-1 to merge. It also waits for D's #94 implementation, if the user rules
  for one (overlap table).
- **Files** `apps/output/views.py`, `metrics/curated/defects.yml`, `CLAUDE.md`,
  `e2e/tests/seeded/output-m3u.spec.ts` and `xc-live.spec.ts` (pin flips), comment-only
  `e2e/tests/seeded/parse-fixture.spec.ts:51-54`, `e2e/COVERAGE.md`, two new test modules.
- **Labels** `apps.output.tests`.
- **Tasks.**
  1. #80: write `test_m3u_attribute_quoting.py`. At seed `tvg-name` is truncated at the inner quote.
     Apply Appendix H. Green.
     **Break-check:** skip `_m3u_attr` for `group_title` only. The group-title assertion alone must
     redden.
  2. #85: write `test_xc_live_categories_user_level.py`. At seed the category is missing. Fix
     `:593`. Green.
     **Break-check:** `__lt` instead of `__lte`. The positive test must redden.
  3. e2e: flip both pins (constraint 11) and make the comment rewrites.
  4. Ledger: `m3u-unescaped-quote` (`defects.yml:19`) and `output-user-level-exact` (`:14`) become
     fixed. Their `test` paths stay. Validate. `e2e/COVERAGE.md` rows for #80 (`:53`, `:68`) and
     #85 (`:64`) record the fix.
  5. CLAUDE.md (constraint 10): in the channel-authorization bullet, delete the clause
     "; `output/views.py` uses `"channels__user_level": 0` instead of `__lte`", keeping the
     sentence's full stop.
  6. Run `apps.output.tests` whole, then once without `--keepdb`.
- **Pin flips, before and after.**

  | test | before | after |
  |---|---|---|
  | `output-m3u.spec.ts` `'a channel name containing a double quote still produces a well-formed EXTINF line (#80)'` | `test.fail(...)`; fails at `mine!.wellFormed` | `test(...)`; `wellFormed` true, `decodeXmlEntities(tvg-name)` and `decodeXmlEntities(title)` equal the quoted name |
  | `xc-live.spec.ts` `'a profiled user sees the category of every channel it can list'` | `test.fail(...)`; final `toContain(String(group.id))` fails | `test(...)`; same assertions, pass |

- **Upstreamable** yes.
- **PR description draft.**

  > **fix(output): escape double quotes in #EXTINF attributes, and apply the user-level ceiling to profiled XC categories (#80, #85)**
  >
  > A `"` in a channel or group name closed its `#EXTINF` attribute early and corrupted the rest of
  > the line for every client; quoted attribute values now carry `&quot;` (and only that — `&` is
  > left literal, because players and Dispatcharr's own importer read M3U attributes verbatim). The
  > display title after the comma is unchanged. `get_live_categories` filtered profiled users'
  > channels with `user_level == 0` where every other branch uses `<=`, so a level-1 user saw level-1
  > streams whose category was missing. Closes #80, #85. Break-checks: <paste>. e2e: both pins
  > flipped (before <run URL>, after <run URL>).
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-8: `fix/E-8-api-404-tls-token`

- **Closes** #57, #128 and #12.
- **Files** `dispatcharr/urls.py`, `dispatcharr/settings.py`, `apps/accounts/api_views.py`,
  `e2e/tests/seeded/token-refresh-deleted-user.spec.ts` (pin flip), comment-only e2e edits listed
  under #12, `e2e/COVERAGE.md`, three new test modules.
- **Labels** all fifteen. `dispatcharr/` is a shared prefix, and
  `python scripts/ci_backend_test_labels.py dispatcharr/urls.py` returns the full set. That is why
  #12, which alone would be one label, rides here rather than in a PR of its own.
- **Tasks.**
  1. #57: write `test_unmatched_api_paths_404.py`. At seed the resolver test fails on
     `TemplateView`. Apply Appendix E. Green.
     **Break-check:** move the new route below the catch-alls. The resolver test must redden.
  2. #128: write `test_tls_cert_path_validation.py`. At seed it ERRORs with `PermissionError`. Apply
     Appendix F. Green.
     **Break-check:** narrow the `except` to `FileNotFoundError`. The test must redden with
     `PermissionError`.
  3. #12: write `test_token_refresh_deleted_user.py`. At seed it ERRORs with `User.DoesNotExist`.
     Apply Appendix G. Green.
     **Break-check:** remove the `except` clause. The test must redden with
     `User.DoesNotExist: User matching query does not exist.`
  4. e2e: flip `token-refresh-deleted-user.spec.ts:69` (constraint 11) and make the comment-only
     edits. `e2e/COVERAGE.md` rows for #12 (`:69`) and #128 (`:153`) record the fix.
  5. Run all fifteen labels (one per container run, constraint 6), then once without `--keepdb`.
     `apps.proxy.tests` must pass unmodified, which confirms that `_surface_for`'s answer for
     unmatched URIs is unchanged.
- **Pin flip, before and after.**

  | test | before | after |
  |---|---|---|
  | `token-refresh-deleted-user.spec.ts` `'refreshing a deleted user\'s token returns 401, not 500'` | `test.fail(...)`; `toBe(401)` fails on 500 | `test(...)`; same assertions, pass |

- **Upstreamable** yes.
- **PR description draft.**

  > **fix: 404 for unmatched /api/ paths, a readable error for an unreadable TLS cert, and 401 for a deleted user's refresh token (#57, #128, #12)**
  >
  > An unmatched `/api/…` path fell through to the SPA catch-all and answered 200 with `index.html`;
  > it is now a JSON 404. That includes `/api/` itself, which has no root route. `_validate_tls_cert_paths` let `Path.is_file()`'s `PermissionError`
  > escape as an import-time traceback; an unreadable certificate now raises the same
  > `ImproperlyConfigured` a missing one does, naming the variable and the reason. A refresh token
  > naming a deleted user now gets the 401 `token_not_valid` every other invalid token gets, not a
  > 500 (simplejwt 5.5.1's bare `.get()`). Closes #57, #128, #12. Break-checks: <paste>. e2e: the
  > #12 pin is flipped (before <run URL>, after <run URL>).
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR E-9: `fix/E-9-recurring-end-date-cap`

- **Closes** #138.
- **Gate lifted.** Open question Q2 was answered on 2026-09-24: the serializer caps `end_date` at
  365 days from today; `sync_recurring_rule_impl` (`apps/channels/tasks.py:861-953`) is not touched
  and full materialisation to `end_date` stays. This section was re-planned that day against
  `50b69c83`, which carries every seed line unchanged (the per-issue analysis says so).
- **Files** `apps/channels/serializers.py` (imports `:1-2` and `:19`; a constant and a helper above
  `:813`; one block after `:847`), `apps/channels/tests/test_recurring_rule_end_date_cap.py` (new),
  comment-only `e2e/tests/dvr/recurring-rules.spec.ts:24-91`, `e2e/COVERAGE.md:165`. **Not**
  `apps/channels/tasks.py`: the files table above still lists `:888-895` for E-9 from the default
  plan and is superseded by this section.
- **Labels** `apps.channels.tests` (`scripts/ci_backend_test_labels.py` on the four paths returns
  exactly that list; the two e2e paths add nothing).
- **Tasks.**
  1. Extract Appendix J's fenced block verbatim and apply it (`git apply --check` first; the block
     was applied clean to a fresh `git archive 50b69c83` export). Run
     `apps.channels.tests.test_recurring_rule_end_date_cap`: exactly two tests fail,
     `…_refused_before_it_materialises_anything` with `AssertionError: 201 != 400` and
     `…_extends_end_date_past_the_cap_…` with `AssertionError: 200 != 400`; the three controls pass.
     That is the red; an `ImportError` here is not.
  2. Extract and apply Appendix I the same way. Green: `Ran 5 tests`, `OK` (2.0 s on the prototype).
     **Break-check 1:** change `if end_date > latest:` to `if end_date >= latest:`.
     `test_a_rule_exactly_at_the_cap_is_accepted` must redden with
     `AssertionError: 400 != 201 : b'{"end_date":["End date must be no more than 365 days from today (<date> at the latest)"]}'`.
     Revert. **Break-check 2:** change `if "end_date" in attrs and end_date:` to `if end_date:`.
     `test_a_patch_that_leaves_end_date_alone_is_not_re_capped` must redden with
     `AssertionError: 400 != 200` and the same body. Revert. Both ran on the prototype and failed
     exactly so; record both lines in the PR description.
  3. Rewrite the "Brief vs. source" section of `recurring-rules.spec.ts`' header (`:24-91`,
     comment-only; every assertion and the 14-day `end_date` stay). It must say: the serializer caps
     `end_date` at `RECURRING_RULE_MAX_DAYS` (365) days from today in the system time zone
     (`apps/channels/serializers.py`, #138); an in-cap rule still materialises every matching day to
     `end_date` synchronously, so the row-count reasoning below it is unchanged; and this test's
     14-day window sits inside the cap by choice. Rewrite `e2e/COVERAGE.md:165` from `known-bug` to
     `done`: the horizon branch is still dead on the REST path by design (`6536f35d`), the request is
     bounded by the serializer's cap instead, fixed in this PR.
  4. `python scripts/check_credential_logging.py apps/channels/serializers.py` (the edit hook runs
     it; zero findings on the prototype). Run `apps.channels.tests` whole with `--keepdb` (348
     tests, `OK` on the prototype), then once without `--keepdb` before push (constraint 6).
- **Ledger.** No `metrics/curated/defects.yml` row names #138 (constraint 8); no parity-matrix row.
- **Upstreamable** yes: upstream `dev`'s serializer carries the same `validate`, and the fix keeps
  `6536f35d`'s branch.
- **PR description draft.**

  > **fix(dvr): cap a recurring rule's end_date at 365 days from today (#138)**
  >
  > Creating or editing a recurring rule over REST materialises a `Recording`, a `ClockedSchedule`
  > and a `PeriodicTask` for every matching day up to `end_date`, synchronously, inside the request.
  > Measured in the test DB: 365 days took under 6 s and ten years 105 s, against the API process's
  > 120 s `harakiri`. The serializer now refuses an `end_date` more than 365 days from today (system
  > time zone) with a field error naming the latest accepted date, on create and on any PATCH that
  > sets `end_date`. **This keeps full materialisation to `end_date` and reverses nothing upstream:**
  > `sync_recurring_rule_impl` and the branch `6536f35d` added are untouched, and a rule within the
  > cap still materialises its whole run. A PATCH that does not carry `end_date` is not re-capped,
  > so a row created before this change keeps toggling and re-syncing. No frontend change: both
  > forms already show the server's message. Ruling: Q2 of the category E plan, 2026-09-24.
  > New module `test_recurring_rule_end_date_cap.py`: two tests red at base, three controls.
  > Break-checks: <paste both lines>. No existing test changed. Closes #138.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Decision memos

None. No rule-4 policy item (#82, #94, #16, #277, #109, #133) is in category E.

---

## Coverage table

| issue | disposition | PR section |
|---|---|---|
| 232 | fix | E-2 |
| 257 | fix (premise corrected: the named viewset is unrouted; default scope per Q1) | E-2 |
| 140 | fix | E-4 |
| 138 | fix (Q2 answered 2026-09-24: the serializer caps `end_date` at 365 days from today) | E-9 |
| 132 | fix | E-3 |
| 131 | fix | E-3 |
| 128 | fix | E-8 |
| 135 | fix (not a duplicate of #71) | E-3 |
| 71 | fix | E-3 |
| 72 | fix | E-4 |
| 7 | fix | E-1 |
| 6 | duplicate of #7, closed; covered by the same change | E-1 |
| 12 | fix | E-8 |
| 15 | fix | E-6 |
| 56 | fix | E-5 |
| 60 | fix | E-5 |
| 70 | fix | E-5 |
| 80 | fix (default per Q3) | E-7 |
| 85 | fix | E-7 |
| 57 | fix | E-8 |
| 177 | fix | E-1 |
| 297 | duplicate of #177, closed; covered by the same change | E-1 |

---

## Open questions for the user

Each has a default that this plan already adopts; answer only to override it.

1. **#257 scope.** The issue's named path, `ProxySettingsViewSet`, is not routed, and the UI already
   merges defaults. Default: make the real write path (`/api/core/settings/<id>/`) validate
   `proxy_settings` through `ProxySettingsSerializer` over the effective value, so saves store all
   seven keys and out-of-range values get a 400, and delete the dead viewset. Alternative: close
   #257 as not reproducible and delete only the dead viewset. That leaves proxy-settings writes
   unvalidated, which is then a new issue.
2. **#138 policy.** **Answered 2026-09-24.** The user rejected the default (every sync, REST
   included, materialises at most the 14-day horizon and the hourly maintainer rolls it forward;
   it would change what the Upcoming list shows for a long rule) and adopted the alternative: keep
   full materialisation to `end_date` (the upstream author added that branch deliberately in
   `6536f35d`) and have the serializer cap `end_date`. E-9 implements the cap at 365 days from
   today; the #138 analysis carries the measurement behind that number, and
   `sync_recurring_rule_impl` is not touched.
3. **#80 escaping form.** Default: replace `"` with `&quot;` in attribute values only. Alternatives:
   `html.escape(quote=True)`, which also turns `&`, `<`, `>` and `'` into entities and makes
   "AT&T" read `AT&amp;T` in players that do not decode; or substitute a typographic quote, which
   every player displays cleanly but which does not round-trip, so the e2e pin's second assertion
   would have to change under rule 5.

Deferred to another plan's question: whether migration paths should route to more backend labels
(C-Q3) also decides how often E-1's `makemigrations --check` test runs on PRs.

## Follow-ups noted, not planned

None of these is a tracked issue in this category.

- `apps/channels/api_views.py:3165` (profile bulk-edit) can still race a concurrent create on
  `ChannelProfileMembership`. It needs a design, because it writes caller-chosen values.
- An advisory lock around schedule-row creation would prevent duplicate inserts, not just survive
  them. `revoke_task` (`apps/channels/signals.py:300-305`) can also delete a shared
  `ClockedSchedule` another save is about to reference.
- The "Entire series + rule" action on title-grouped recurring-rule cards posts an empty `tvg_id`
  and fails silently with a 400 (#71's comment).
- `" Auto-sync: N failed."` (`RANGE_EXHAUSTED`) still ends a refresh at SUCCESS.
- `BaseConfig.get_proxy_settings` closes the DB connection in its `finally` (`apps/proxy/config.py:60-65`)
  on every uncached call. That is why the new test must patch it.
- The proxy-settings defaults still exist as a DB-failure fallback copy in `apps/proxy/config.py:50-58`
  and as `getProxySettingDefaults()` in the frontend (`frontend/src/utils/forms/settings/ProxySettingsFormUtils.js:10-20`).
- `e2e/tests/streaming-failover/failover-buffering.spec.ts`'s 12-second cache sleep and its header,
  and `catchup-redirect.spec.ts:33-38`, describe the process-local cache as on the live path. After
  E-2 the sleep is unnecessary but harmless.
- simplejwt could be upgraded, and deleting a user could blacklist their outstanding refresh tokens
  (#12's note).

---

## Appendix A: E-2, `BaseConfig`'s cache (against `a54b09a9`)

```diff
@@ apps/proxy/config.py (:19)
-    # Cache for proxy settings (class-level, shared across all instances).
-    # Backed by CoreSettings Redis group cache; this local copy avoids Redis
-    # chatter inside the proxy hot path. Cleared when proxy_settings is saved.
+    # Process-local cache for proxy settings: ONE copy per process, always on
+    # BaseConfig. Every method below names BaseConfig explicitly, never cls:
+    # `cls._proxy_settings_cache = ...` reached through TSConfig used to create
+    # a TSConfig attribute that shadowed this one, and the save-time
+    # invalidation (CoreSettings.invalidate_group_cache ->
+    # BaseConfig.clear_proxy_settings_cache) never cleared it (#232).
     _proxy_settings_cache = None
     _proxy_settings_cache_time = 0
     _proxy_settings_cache_ttl = 10  # Cache for 10 seconds

     @classmethod
     def clear_proxy_settings_cache(cls):
         """Drop process-local proxy settings (called on CoreSettings invalidate)."""
-        cls._proxy_settings_cache = None
-        cls._proxy_settings_cache_time = 0
+        BaseConfig._proxy_settings_cache = None
+        BaseConfig._proxy_settings_cache_time = 0

     @classmethod
     def get_proxy_settings(cls):
         """Get proxy settings from CoreSettings JSON data with fallback to defaults (cached)"""
         # Check if cache is still valid
         now = time.time()
-        if cls._proxy_settings_cache is not None and (now - cls._proxy_settings_cache_time) < cls._proxy_settings_cache_ttl:
-            return cls._proxy_settings_cache
+        cached = BaseConfig._proxy_settings_cache
+        if cached is not None and (now - BaseConfig._proxy_settings_cache_time) < BaseConfig._proxy_settings_cache_ttl:
+            return cached
@@
             settings = CoreSettings.get_proxy_settings()
-            cls._proxy_settings_cache = settings
-            cls._proxy_settings_cache_time = now
+            BaseConfig._proxy_settings_cache = settings
+            BaseConfig._proxy_settings_cache_time = now
             return settings
```

`BaseConfig` is the enclosing class, resolved at call time from module globals, so no import is
added. J-3's static pin still sees exactly one model import. `get_redis_chunk_ttl` and the
`TSConfig` getters keep calling `cls.get_proxy_settings()`, which is correct now.

**CLAUDE.md replacement text (E-2 step 7):**

> **`proxy_settings` has two caches, and neither is stale on a live tune.** The `next-source`
> answer reads `CoreSettings.get_proxy_settings()` (`apps/proxy/next_source.py`'s
> `_with_proxy_settings`, Amendment A1.4) — the Redis group cache, invalidated for every process by
> the `post_save` receiver — so a threshold change reaches the next tune at once, and still must
> land before the channel starts. `apps/proxy/config.py` keeps a second, process-local 10-second
> copy on `BaseConfig` for `ConfigHelper`'s database-backed getters, which no production path calls
> since stage 2d-4; saving clears it in the process that handled the write and the TTL ends it in
> the others. Until #232 it cleared in no process at all: readers went through `TSConfig`, and
> `cls.` assignment in the inherited classmethod created a `TSConfig` attribute shadowing the one
> the receiver cleared.

## Appendix B: E-2, validating `proxy_settings` on the real write path (against `a54b09a9`)

```diff
@@ core/serializers.py (:6)
-from .models import CoreSettings, UserAgent, StreamProfile, OutputProfile, DVR_SETTINGS_KEY, NETWORK_ACCESS_KEY
+from .models import CoreSettings, UserAgent, StreamProfile, OutputProfile, DVR_SETTINGS_KEY, NETWORK_ACCESS_KEY, PROXY_SETTINGS_KEY
@@ core/serializers.py, CoreSettingsSerializer.update, immediately before `result = super().update(...)` (:86)
+        # #257: the settings page writes proxy_settings HERE, not through
+        # core/api_views.py's ProxySettingsViewSet (never routed, now deleted).
+        # Validate the effective value -- stored group merged over code
+        # defaults, then the incoming keys -- so a save stores all seven keys
+        # and an out-of-range value is refused rather than stored.
+        if instance.key == PROXY_SETTINGS_KEY and "value" in validated_data:
+            validated_data["value"] = _validated_proxy_settings(validated_data["value"])
+
         result = super().update(instance, validated_data)
@@ core/serializers.py, module level, after ProxySettingsSerializer
+def _validated_proxy_settings(value):
+    if not isinstance(value, dict):
+        raise serializers.ValidationError({"value": "proxy_settings must be an object."})
+    serializer = ProxySettingsSerializer(
+        data={**CoreSettings.get_proxy_settings(), **value}
+    )
+    if not serializer.is_valid():
+        raise serializers.ValidationError({"value": serializer.errors})
+    return dict(serializer.validated_data)
```

`core/api_views.py`: delete `class ProxySettingsViewSet` (`:206-280`) and `ProxySettingsSerializer,`
from the import block (`:23-31`). `grep -rn "ProxySettingsViewSet" --include='*.py' .` must then
print only the rewritten docstring line in `apps/proxy/serializers.py`.

## Appendix C: E-1, `get_or_create_schedule` (against `a54b09a9`)

```diff
@@ core/scheduling.py, after logger (:13)
+def get_or_create_schedule(model, **lookup):
+    """get_or_create for django_celery_beat's schedule tables.
+
+    IntervalSchedule, CrontabSchedule and ClockedSchedule carry no uniqueness
+    constraint beyond the primary key, so Django's get_or_create has no
+    IntegrityError to fall back on: two concurrent callers both insert, and
+    every later get() raises MultipleObjectsReturned -- a permanent 500 on
+    source creation (#7) or a silently unscheduled recording (#131). Take
+    the oldest matching row instead; a concurrent insert can still add a
+    duplicate, but a duplicate is no longer fatal. A never-chosen duplicate
+    stays in the table, harmlessly: the orphan cleanups below run only on a
+    task's previous schedule, not as a sweep.
+    """
+    existing = model.objects.filter(**lookup).order_by("id").first()
+    if existing is not None:
+        return existing
+    return model.objects.create(**lookup)
+
@@ core/scheduling.py (:91)
-        crontab, _ = CrontabSchedule.objects.get_or_create(
+        crontab = get_or_create_schedule(
+            CrontabSchedule,
             minute=cron_parts["minute"],
@@ core/scheduling.py (:121)
-        interval, _ = IntervalSchedule.objects.get_or_create(
+        interval = get_or_create_schedule(
+            IntervalSchedule,
             every=max(int(interval_hours), 1) if interval_hours else 1,
```

E-3 then applies `clocked = get_or_create_schedule(ClockedSchedule, clocked_time=eta)` at
`apps/channels/signals.py:271`, importing from `core.scheduling`. That module imports only
`core.models` and `django_celery_beat`, so the import adds no cycle.

## Appendix D: E-5, refresh outcomes (against C-3's shape; seed lines cited)

```diff
@@ apps/m3u/tasks.py, module level near _NON_TERMINAL_REFRESH_STATUSES (:42)
+# Third element of refresh_m3u_groups' failure tuple when it did NOT run
+# (group-refresh lock held by another task, or the account is missing or
+# inactive): not a failure, and the caller must not report one (#56). Every
+# other (message, None) return has already recorded its specific error on
+# the account (#60). Success still returns a plain 2-tuple.
+GROUP_REFRESH_SKIPPED = "skipped"
@@ refresh_m3u_groups, outer function after C-3 (seed :1555)
-        return f"Task already running for account_id={account_id}.", None
+        return (
+            "Refresh skipped: another refresh of this account's groups is already running.",
+            None,
+            GROUP_REFRESH_SKIPPED,
+        )
@@ _refresh_m3u_groups_locked after C-3 (seed :1565)
-        return f"M3UAccount with ID={account_id} not found or inactive.", None
+        return (
+            "Refresh skipped: the account was deleted or deactivated.",
+            None,
+            GROUP_REFRESH_SKIPPED,
+        )
@@ _refresh_single_m3u_account_impl (seed :3503-3517)
             if not result or result[1] is None:
+                if result and len(result) > 2 and result[2] == GROUP_REFRESH_SKIPPED:
+                    logger.info(
+                        f"Group refresh skipped for account {account_id}: {result[0]}"
+                    )
+                    _set_m3u_account_status(account_id, M3UAccount.Status.IDLE, result[0])
+                    return result[0]
                 logger.error(
                     f"Failed to refresh M3U groups for account {account_id}: {result}"
                 )
-                error_msg = (
-                    "Failed to refresh M3U groups - download failed or other error"
-                )
-                _set_m3u_account_status(
-                    account_id,
-                    M3UAccount.Status.ERROR,
-                    error_msg,
-                    notify_error=True,
-                    ws_error=error_msg,
-                )
+                recorded = (
+                    M3UAccount.objects.filter(id=account_id)
+                    .values_list("status", flat=True)
+                    .first()
+                ) == M3UAccount.Status.ERROR
+                if not recorded:
+                    error_msg = (
+                        result[0]
+                        if result and isinstance(result[0], str) and result[0]
+                        else "Failed to refresh M3U groups - download failed or other error"
+                    )
+                    _set_m3u_account_status(
+                        account_id,
+                        M3UAccount.Status.ERROR,
+                        error_msg,
+                        notify_error=True,
+                        ws_error=error_msg,
+                    )
                 return "Failed to update m3u account - download failed or other error"
```

The skip branch sits above the `logger.error`, so a skip logs at INFO only. The terminal write (seed `:3843-3935`):

```diff
         auto_sync_message = ""
         auto_sync_result = {}
+        auto_sync_failed = False
@@ (:3869)
             elif auto_sync_result.get("status") == "error":
+                auto_sync_failed = True
                 auto_sync_message = (
@@ (:3873)
         except Exception as e:
+            auto_sync_failed = True
+            auto_sync_message = f" Auto-sync error: {str(e)[:200]}."
             logger.error(
@@ (:3891)
-        account.status = M3UAccount.Status.SUCCESS
+        # #70: a failed auto channel sync must not read as a successful
+        # refresh. updated_at still advances: the stream refresh succeeded.
+        account.status = (
+            M3UAccount.Status.ERROR if auto_sync_failed else M3UAccount.Status.SUCCESS
+        )
@@ (:3918)
-            status="success",  # Explicitly set status to success
+            status="error" if auto_sync_failed else "success",
+            **({"error": account.last_message} if auto_sync_failed else {}),
```

C-3's `finally` releases the lock on every return, so no return added here releases anything.

## Appendix E: E-8, the `/api/` 404 (against `a54b09a9`)

```diff
@@ dispatcharr/urls.py (:1-5)
+from django.http import JsonResponse
+from django.views.decorators.csrf import csrf_exempt
@@ (before urlpatterns, :14)
+@csrf_exempt
+def api_not_found(request, *args, **kwargs):
+    """#57: an /api/ path the API urlconf does not match is a JSON 404, never
+    the SPA shell. Any method: a POST to a typo'd endpoint is also a 404."""
+    return JsonResponse({"detail": "Not found."}, status=404)
+
+
 urlpatterns = [
     # API Routes
     path("api/", include(("apps.api.urls", "api"), namespace="api")),
+    re_path(r"^api/", api_not_found),
     path("api", RedirectView.as_view(url="/api/", permanent=True)),
```

## Appendix F: E-8, `_validate_tls_cert_paths` (against `a54b09a9`)

```diff
@@ dispatcharr/settings.py (:18-23)
     for env_var, file_path in paths:
-        if file_path and not Path(file_path).is_file():
+        if not file_path:
+            continue
+        try:
+            is_file = Path(file_path).is_file()
+        except OSError as exc:
+            # Python 3.13's Path.is_file() re-raises EACCES from os.stat
+            # instead of returning False (#128).
+            raise ImproperlyConfigured(
+                f"{service_name} TLS: {env_var}={file_path!r} — cannot read file "
+                f"({exc.strerror or exc}). Check that the application user can "
+                f"traverse the directory and read the file."
+            ) from exc
+        if not is_file:
             raise ImproperlyConfigured(
```

## Appendix G: E-8, token refresh (against `a54b09a9`)

```diff
@@ apps/accounts/api_views.py (:151)
-        return super().post(request, *args, **kwargs)
+        try:
+            return super().post(request, *args, **kwargs)
+        except User.DoesNotExist:
+            # simplejwt 5.5.1's TokenRefreshSerializer.validate looks the
+            # token's user up with a bare .get(); a deleted user is an invalid
+            # token (401 token_not_valid), not a server error (#12).
+            raise InvalidToken()
```

Add `from rest_framework_simplejwt.exceptions import InvalidToken`. `User` is already imported
(`apps/accounts/api_views.py:22`, `from .models import User`), and it is the configured user model.

## Appendix H: E-7, `#EXTINF` attribute quoting (against `a54b09a9`)

```diff
@@ apps/output/views.py, above generate_m3u's decorators (:107)
+def _m3u_attr(value):
+    """A value for a double-quoted #EXTINF attribute (#80). Only `"` is
+    escaped: players and apps/m3u/tasks.py's importer read attributes
+    literally, so a general HTML escape would turn "AT&T" into "AT&amp;T"."""
+    return str(value).replace('"', "&quot;")
+
@@ (:298-306)
             tvc_guide_stationid = (
-                f'tvc-guide-stationid="{effective_tvc_guide}" '
+                f'tvc-guide-stationid="{_m3u_attr(effective_tvc_guide)}" '
             )
         extinf_line = (
-            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
-            f'tvg-chno="{formatted_channel_number}" {tvc_guide_stationid}group-title="{group_title}",{effective_name}\n'
+            f'#EXTINF:-1 tvg-id="{_m3u_attr(tvg_id)}" tvg-name="{_m3u_attr(tvg_name)}" '
+            f'tvg-logo="{_m3u_attr(tvg_logo)}" tvg-chno="{_m3u_attr(formatted_channel_number)}" '
+            f'{tvc_guide_stationid}group-title="{_m3u_attr(group_title)}",{effective_name}\n'
         )
```

## Appendix I: E-9, the `end_date` cap (against `50b69c83`)

A real unified diff, unlike Appendices A-H: extract the fenced block verbatim and `git apply --check` it
from the repository root. It was applied clean to a fresh `git archive 50b69c83` export, and the result
was byte-identical to the prototype that produced the red, green and break-check runs above.

```diff
--- a/apps/channels/serializers.py
+++ b/apps/channels/serializers.py
@@ -1,5 +1,6 @@
 import json
-from datetime import datetime
+from datetime import datetime, timedelta
+from zoneinfo import ZoneInfo
 
 from rest_framework import serializers
 from .models import (
@@ -16,7 +17,7 @@
     RecurringRecordingRule,
 )
 from apps.epg.serializers import EPGDataSerializer
-from core.models import StreamProfile
+from core.models import CoreSettings, StreamProfile
 from apps.epg.models import EPGData
 from django.db import connection, transaction
 from django.urls import reverse
@@ -808,6 +809,26 @@
             raise serializers.ValidationError("End time must be after start time.")
 
         return data
+
+
+# A recurring rule materialises one Recording (and one ClockedSchedule/PeriodicTask
+# pair) per matching day up to its own end_date, synchronously, inside the request:
+# sync_recurring_rule_impl's 14-day horizon never applies on the REST path
+# (upstream 6536f35d made end_date required and full materialisation deliberate).
+# The request is bounded here instead (#138). Measured in the test DB: 365 days
+# took under 6 s per request and ten years 105 s, against a 120 s API harakiri.
+RECURRING_RULE_MAX_DAYS = 365
+
+
+def _system_local_today():
+    """Today in the configured system time zone, as sync_recurring_rule_impl computes
+    local_today (apps/channels/tasks.py), so the cap and the walk share a calendar."""
+    tz_name = CoreSettings.get_system_time_zone()
+    try:
+        tz = ZoneInfo(tz_name)
+    except (KeyError, ValueError, TypeError):
+        tz = timezone.get_current_timezone()
+    return timezone.now().astimezone(tz).date()
 
 
 class RecurringRecordingRuleSerializer(serializers.ModelSerializer):
@@ -845,6 +866,19 @@
             existing_end = getattr(self.instance, "end_date", None)
             if existing_end is None:
                 raise serializers.ValidationError("End date is required")
+        # Only a request that sets end_date is capped: a row from before the cap keeps
+        # its end_date on a PATCH that does not touch it (the operator can shorten it).
+        if "end_date" in attrs and end_date:
+            latest = _system_local_today() + timedelta(days=RECURRING_RULE_MAX_DAYS)
+            if end_date > latest:
+                raise serializers.ValidationError(
+                    {
+                        "end_date": (
+                            f"End date must be no more than {RECURRING_RULE_MAX_DAYS} days "
+                            f"from today ({latest.isoformat()} at the latest)"
+                        )
+                    }
+                )
         if start and end and start_date and end_date:
             start_dt = datetime.combine(start_date, start)
             end_dt = datetime.combine(end_date, end)
```

## Appendix J: E-9, `test_recurring_rule_end_date_cap.py` (against `50b69c83`)

Same form as Appendix I; a new file, so `git apply` creates it.

```diff
--- /dev/null
+++ b/apps/channels/tests/test_recurring_rule_end_date_cap.py
@@ -0,0 +1,103 @@
+"""#138: a recurring rule materialises one Recording (and one ClockedSchedule/PeriodicTask
+pair) per matching day up to its own end_date, synchronously, inside the request. The
+serializer caps end_date so the request stays bounded; sync_recurring_rule_impl is unchanged.
+"""
+from datetime import timedelta
+from zoneinfo import ZoneInfo
+
+from django.contrib.auth import get_user_model
+from django.test import TestCase
+from django.utils import timezone
+from django_celery_beat.models import PeriodicTask
+from rest_framework.test import APIClient
+
+from apps.channels.models import Channel, Recording, RecurringRecordingRule
+# The cap is pinned here as a number, deliberately not imported from the serializer.
+from core.models import CoreSettings
+
+RULES_URL = "/api/channels/recurring-rules/"
+CAP_DAYS = 365
+CAP_MESSAGE = f"End date must be no more than {CAP_DAYS} days from today"
+
+
+class RecurringRuleEndDateCapTests(TestCase):
+    def setUp(self):
+        User = get_user_model()
+        self.admin = User.objects.create_user(username="cap_admin", password="pass")
+        self.admin.user_level = 10
+        self.admin.save()
+        self.client = APIClient()
+        self.client.force_authenticate(user=self.admin)
+        self.channel = Channel.objects.create(channel_number=1, name="Cap Channel")
+        # The same "today" sync_recurring_rule_impl walks from (apps/channels/tasks.py).
+        tz = ZoneInfo(CoreSettings.get_system_time_zone())
+        self.today = timezone.now().astimezone(tz).date()
+
+    def _payload(self, **overrides):
+        payload = {
+            "channel": self.channel.id,
+            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
+            "start_time": "12:00:00",
+            "end_time": "13:00:00",
+            "start_date": (self.today - timedelta(days=2)).isoformat(),
+            "end_date": (self.today + timedelta(days=14)).isoformat(),
+            "name": "cap",
+        }
+        payload.update(overrides)
+        return payload
+
+    def _rows_for(self, rule_id):
+        return Recording.objects.filter(custom_properties__rule__id=rule_id).count()
+
+    def test_a_rule_past_the_cap_is_refused_before_it_materialises_anything(self):
+        over = (self.today + timedelta(days=CAP_DAYS + 1)).isoformat()
+        resp = self.client.post(RULES_URL, self._payload(end_date=over), format="json")
+        self.assertEqual(resp.status_code, 400, resp.content)
+        self.assertIn(CAP_MESSAGE, " ".join(resp.json().get("end_date", [])))
+        self.assertEqual(RecurringRecordingRule.objects.count(), 0)
+        self.assertEqual(Recording.objects.count(), 0)
+        self.assertEqual(PeriodicTask.objects.filter(name__startswith="dvr-recording-").count(), 0)
+
+    def test_a_rule_exactly_at_the_cap_is_accepted(self):
+        at = (self.today + timedelta(days=CAP_DAYS)).isoformat()
+        resp = self.client.post(RULES_URL, self._payload(end_date=at), format="json")
+        self.assertEqual(resp.status_code, 201, resp.content)
+        self.assertGreaterEqual(self._rows_for(resp.json()["id"]), CAP_DAYS)
+
+    def test_a_create_with_no_end_date_is_still_refused_as_required(self):
+        payload = self._payload()
+        del payload["end_date"]
+        resp = self.client.post(RULES_URL, payload, format="json")
+        self.assertEqual(resp.status_code, 400, resp.content)
+        self.assertIn("End date is required", resp.content.decode())
+        self.assertEqual(RecurringRecordingRule.objects.count(), 0)
+
+    def test_a_patch_that_leaves_end_date_alone_is_not_re_capped(self):
+        # A row from before the cap, with an end_date the cap would now refuse.
+        rule = RecurringRecordingRule.objects.create(
+            channel=self.channel,
+            days_of_week=[0, 1, 2, 3, 4, 5, 6],
+            start_time="12:00:00",
+            end_time="13:00:00",
+            start_date=self.today,
+            end_date=self.today + timedelta(days=CAP_DAYS + 30),
+        )
+        resp = self.client.patch(f"{RULES_URL}{rule.id}/", {"enabled": False}, format="json")
+        self.assertEqual(resp.status_code, 200, resp.content)
+        rule.refresh_from_db()
+        self.assertFalse(rule.enabled)
+        self.assertEqual(rule.end_date, self.today + timedelta(days=CAP_DAYS + 30))
+
+    def test_a_patch_that_extends_end_date_past_the_cap_is_refused_and_changes_nothing(self):
+        resp = self.client.post(RULES_URL, self._payload(), format="json")
+        self.assertEqual(resp.status_code, 201, resp.content)
+        rule_id = resp.json()["id"]
+        before = self._rows_for(rule_id)
+        self.assertGreaterEqual(before, 13)
+        over = (self.today + timedelta(days=CAP_DAYS + 1)).isoformat()
+        resp = self.client.patch(f"{RULES_URL}{rule_id}/", {"end_date": over}, format="json")
+        self.assertEqual(resp.status_code, 400, resp.content)
+        self.assertIn(CAP_MESSAGE, " ".join(resp.json().get("end_date", [])))
+        rule = RecurringRecordingRule.objects.get(pk=rule_id)
+        self.assertEqual(rule.end_date, self.today + timedelta(days=14))
+        self.assertEqual(self._rows_for(rule_id), before)
```
