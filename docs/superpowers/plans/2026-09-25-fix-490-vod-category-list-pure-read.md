# Fix plan — #490, `VODCategoryViewSet.list()` becomes a pure read

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** `GET /api/vod/categories/` stops writing. Today `VODCategoryViewSet.list()` creates the
movie and series `Uncategorized` categories, and a relation to each for every active XC account with
VOD enabled, on every call. After this plan the list only reads. The relations are created where VOD
is turned on for an account (account create and the update that enables VOD) and, as today, by every
VOD refresh. A backend test pins "the list writes nothing", and the e2e `m3u_account`-filter pin goes
back to an exact answer.

**Issue.** #490 (planned here). This plan closes nothing. The implementation PR carries the closing
line for #490.

**Seed SHA: `93d1e424`** (`main`, 2026-09-25). Every `file:line` below was opened there. The whole
change in the appendices was applied to the seed, run in a private test container (`plan-490`, mounted
at the planner's worktree, never the shared `dispatcharr-testrunner`), break-checked edit by edit, and
reverted. Only this document is committed.

**Architecture.** Django 6 + DRF control plane. Three production files change, all in the API process:
`apps/vod/api_views.py` (the list override is deleted), `apps/vod/tasks.py` (one new helper,
`ensure_uncategorized_relations`) and `apps/m3u/api_views.py` (create and update call the helper).
No model, no migration, no Celery task signature, no frontend, no Go, no `docker/`, no workflow.
**Not on the live relay path**: the Go relay never touches VOD categories, so the relay parity matrix
does not apply.

**Tech stack.** Python 3.13, Django 6, DRF, `django.test.utils.CaptureQueriesContext` for the pin.
Playwright/TypeScript for two existing e2e specs (one assertion tightened, comments corrected).

**Spec.** There is no phase spec. The authority is the issue body, read in full:
`gh issue view 490 --repo D10Scot/Dispatcharr`. Where the issue was silent, or wrong, the ruling is in
§ Per-issue analysis, each with its reason. Other authorities cited: `CLAUDE.md` (§ Test hooks,
§ Testing, § Conventions, § Known defects), `docs/adr/0002-e2e-test-taxonomy.md` (both touched e2e
tests keep their `@contract` tag), `docs/adr/0003` (no settings group is written, so no blast radius),
`docs/agents/metrics.md` (§ Metrics dashboard below), `docs/agents/issue-tracker.md` (`--repo` on
every `gh` call).

**Planner's worktree.** `/Users/dion/git/Dispatcharr/.worktrees/plan-490`, branch
`docs/plan-490-vod-category-pure-read`. Only this file is committed.

---

## Global constraints

Numbered so a step can cite one. **A conflict between a constraint and a step is a STOP and report,
never a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's
   cwd is correlated across concurrent agents (`CLAUDE.md` § Repository and direction). Below,
   `WT=/Users/dion/git/Dispatcharr/.worktrees/fix-490`.
2. **`set -o pipefail`** on any pipeline whose exit status you read. Never `2>/dev/null` a git query
   you interpret. Write `git show "${ref}:path"` with braces (the zsh modifier trap).
3. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit with
   `git -C "$WT" commit -F <file>`. The commit gate matches on command text, so a heredoc or message
   containing both words trips it.
4. **Test-modification rule.** A test may change only when the behaviour it pins is the thing being
   changed, and every such change is listed with its before and after (§ Test modifications). Never
   widen a tolerance, raise a timeout, lower a count or delete an assertion to make a run green. New
   behaviour gets a new test named after the defect. This PR changes exactly one existing assertion's
   predicate and adds one assertion; every other existing-test edit is a comment.
5. **The appendices are the deliverable, verbatim.** Extract them with § Appendix extraction and apply
   them with `git apply`. Do not retype them. If `git apply --check` refuses one, STOP and report the
   refusal: `main` has moved under this plan, and the plan needs a re-seed, not an improvised patch.
6. **Test container.** The `PostToolUse` hooks fire on the Write/Edit tools only, and always against
   the shared container `dispatcharr-testrunner`, whose bind mount decides which tree is tested
   (`CLAUDE.md` § Test hooks). This plan applies every change with `git apply` from Bash, so no hook
   fires, and you run the checks yourself in a **private** container, `fix-490`:

   ```bash
   DISPATCHARR_TEST_CONTAINER=fix-490 DISPATCHARR_TEST_DB_VOLUME=fix-490-db \
     CLAUDE_HOOK_REPO_ROOT="$WT" "$WT/.claude/hooks/start-test-container.sh"
   ```

   Run a label or module with the hook's own environment (this is `run-affected-tests.sh`'s `dexec`):

   ```bash
   docker exec -w /repo \
     -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
     -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
     -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
     -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
     fix-490 /dispatcharrpy/bin/python manage.py test <label-or-module> -v1
   ```

   Call that `T <args>` below. Flush Redis before a whole-label run
   (`docker exec fix-490 redis-cli flushall`), as the hook and CI do. Run each label **once without
   `--keepdb`** (add `--noinput`, or the runner stops to ask about the existing test database) before
   push: the seeded-row drift trap. If you ever edit a `tests/test_*.py` file with the Edit tool, its
   hook will refuse loudly on the mount mismatch; that refusal is expected and is not a test result.
7. **No `models.py` edit, no migration, no data migration, no management command** (ruling D6). No
   frontend edit (§ Frontend). No `metrics/curated/` edit (§ Metrics dashboard). No `CLAUDE.md` edit:
   it never mentions the list write (`grep -n "vod/categor\|VODCategoryViewSet" CLAUDE.md` prints
   nothing at seed).
8. **Branch** `fix/490-vod-category-list-pure-read`, worktree `.worktrees/fix-490`. Nothing under
   `docker/` or `relay/` changes, so no `migration/` prefix.
9. **No closing keyword in any commit message.** The closing line for #490 goes in the implementation
   PR's description only, where the draft below marks its place.
10. **Never touch** `dispatcharr-testrunner`, `dispatcharr-e2e`, `e2e-upstream` or any container,
    volume or network another agent named. Remove `fix-490`, `fix-490-db` and the private e2e stack
    (Task 4) when done.

---

## Files this plan touches

Anchors are at seed `93d1e424`.

| File | Anchor at seed | Change | Appendix |
|---|---|---|---|
| `apps/vod/tasks.py` | `:20-27` `_empty_categories_should_abort`; new helper inserted after `:27` | add `ensure_uncategorized_relations(account)` | A |
| `apps/vod/api_views.py` | `:16-19` model import; `:647-698` `VODCategoryViewSet.list` | delete the override; drop the now-unused `M3UVODCategoryRelation` import | B |
| `apps/m3u/api_views.py` | `:136-144` `create`'s XC branch; `:197-244` `update`'s enable-VOD branch, inline creation at `:202-239` | `create` calls the helper; `update`'s inline block becomes a read-back plus the helper | C |
| `apps/vod/tests/test_vod_category_list_pure_read.py` | new | the pure-read pin | D |
| `apps/m3u/tests/test_vod_uncategorized_relations.py` | new | the create/update pins | E |
| `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` | `:333-350` (comment `:333-344`, waiter `:345-350`) | exact five-row predicate plus one `toEqual`; comment rewritten | F |
| `e2e/tests/seeded/vod-category-gating.spec.ts` | `:269-275`, `:301-306`, `:312-315` | comments only | G |
| `e2e/README.md` | `:362-367` | the "writes rows on every call" paragraph rewritten | H |
| `e2e/COVERAGE.md` | new row after `:98` (the #96 row) | one row recording the retired hazard | I |

Read, not changed (each is cited below): `apps/accounts/permissions.py:42-49`,
`apps/vod/tasks.py:52-127` (`refresh_vod_content`), `:129-181` (`refresh_categories`), `:183-236`
(`refresh_movies`), `:238-291` (`refresh_series`), `:293-419` (`batch_create_categories`),
`:455-465` and `:827-837` (the `__uncategorized__` routing), `apps/vod/models.py:315-333`
(`M3UVODCategoryRelation`, `unique_together = [('m3u_account', 'category')]` at `:333`),
`apps/m3u/signals.py:12-20`, `apps/m3u/tasks.py:4009-4014`, `apps/m3u/serializers.py:270-299` and
`:354-370`, `frontend/src/components/forms/M3UGroupFilter.jsx:54-64`,
`frontend/src/components/forms/VODCategoryFilter.jsx:30-55`, `frontend/src/store/useVODStore.jsx:287-302`.

---

## Overlap with sibling plans

- **Open PRs.** `gh pr list --repo D10Scot/Dispatcharr --state open` on 2026-09-25 listed #496, #498,
  #499, #501, #502, #504, #505, none of which touches any file in the table above (checked with
  `--json files`), and, opened after that listing, **#506** (`fix/468-vod-actors-non-string`). #506 is
  a **same-file, non-conflicting overlap**: it edits `apps/vod/tasks.py` (hunks at `:495` in
  `process_movie_batch` and `:2321` in `refresh_movie_advanced_data`) and adds
  `apps/vod/tests/test_movie_actors_non_string.py`. Appendix A's only hunk sits at `:27`, and #506's
  diff (`gh pr diff 506`) `git apply --check`s cleanly on top of Appendix A at seed. If #506 merges
  first, Task 0 Step 3's `git apply --check` of every appendix against current `main` is the re-check.
- **Merged work already in the seed.** D-4 (#453) edited `apps/vod/api_views.py:624` (the
  `m3u_account` filter) and `vod-ingest-fidelity.spec.ts`; it is the PR that found #490. C-6 (#430)
  edited `apps/vod/tasks.py`. Both are in `93d1e424`.
- **Sibling plans.** `grep -ln "Uncategorized\|VODCategoryViewSet" docs/superpowers/plans/2026-09-2*.md`
  finds nothing at seed. No other plan edits `create`/`update` in `apps/m3u/api_views.py` or
  `refresh_movies`/`refresh_series`; the one recent plan that touched `apps/vod/api_views.py`,
  `2026-09-23-fixplan-D-vod-catchup.md` (D-4, the filter at `:624`), is merged.
- **A parallel planner branch for the same issue exists locally**:
  `docs/plan-490-vod-category-pure-read-b2` (worktree `.worktrees/plan-490-b2`, not pushed when this
  plan was written). I don't know what it plans. Exactly one plan for #490 should be implemented; the
  orchestrator picks.
- **Historical G9 documents** — `docs/superpowers/plans/2026-08-30-e2e-vod-series.md:26`, `:876`,
  `:1008`, `:1990` and `docs/superpowers/specs/2026-08-30-e2e-vod-series-design.md:79`, `:336-339` —
  describe the write-on-GET as it was. They are dated records and are left unedited. The live rule
  lives in `e2e/README.md`, which Appendix H updates. The rule itself ("no G9 test may assert that an
  account lacks an `Uncategorized` relation") stays true after this plan, for a different reason
  (§ Per-issue analysis, ruling D7).

---

## Per-issue analysis: #490

### What the code does at seed

`VODCategoryViewSet.list()` (`apps/vod/api_views.py:647-698`) runs, before the ordinary
`super().list()`:

1. `get_or_create` of `VODCategory(name="Uncategorized", category_type="movie")` and the same for
   `"series"` (`:652-662`), unconditionally, even with no account at all.
2. For every `M3UAccount` with `account_type=XC` and `is_active=True` (`:665-668`) whose
   `custom_properties["enable_vod"]` is truthy (`:671-675`): `get_or_create` of its
   `M3UVODCategoryRelation` to both categories, `enabled` defaulting to
   `custom_properties.get("auto_enable_new_groups_vod", True)` **for both types** (`:677-694`).

Measured on the seed with one such account and a Standard-level caller: the first call issues
**four `INSERT`s** (two categories, two relations). With no such account it would still insert the two
categories, since `:652-662` are unconditional (read, not measured). `get_or_create` is idempotent and
`M3UVODCategoryRelation` is `unique_together` on `(m3u_account, category)` (`apps/vod/models.py:333`),
so later calls insert nothing; they still pay the `SELECT`s: two for the categories, one for the
accounts, and two per enabled account.

### Who can trigger it

`get_permissions` (`apps/vod/api_views.py:641-645`) maps the `list` action through
`permission_classes_by_action` (`apps/accounts/permissions.py:42-43`) to `IsStandardUser`
(`:15-20`, `user_level >= STANDARD`). So **Standard users and Admins** can call it; a **Streamer gets
403** and cannot trigger the write. The planner's brief assumed a Streamer could; that is not true. What is
true is that a non-admin (Standard) user's read writes rows attached to accounts that user has no
authority over — every enabled XC account on the instance.

### Every writer of an `Uncategorized` relation at seed

| Writer | When | Which accounts | `enabled` for a new series relation |
|---|---|---|---|
| `VODCategoryViewSet.list()` `apps/vod/api_views.py:647-698` | every GET | every active XC account with `enable_vod` | `auto_enable_new_groups_vod` (wrong key) |
| `M3UAccountViewSet.update()` `apps/m3u/api_views.py:197-244` | a PUT/PATCH whose top-level `enable_vod` flips false → true on an XC account (PATCH reaches it too: `partial_update` at `:249-265` calls `super().partial_update`, which DRF routes to `self.update`) | that account | `auto_enable_new_groups_vod` (wrong key), read from the **pre-update** `instance` (`:220-221`) |
| `refresh_movies()` / `refresh_series()` `apps/vod/tasks.py:187-210`, `:242-265` | every VOD refresh that got past `refresh_categories` (`:77-86` returns early on `None`) | the refreshed account only | `auto_enable_new_groups_series` (right key) |
| `M3UAccountViewSet.create()` `apps/m3u/api_views.py:136-144` | — | none: it runs `refresh_m3u_groups` and, with `enable_vod`, `refresh_categories` inline, and `refresh_categories` (`apps/vod/tasks.py:129-181`) creates provider categories only | — |

Once created, a relation is never deleted by a refresh: `batch_create_categories` excludes
`Uncategorized` from its orphan sweep (`apps/vod/tasks.py:364-374`).

### What the list write was actually papering over

An **XC account created with VOD on** gets no `Uncategorized` relation from any path until its first
full VOD refresh, and that refresh does not follow the create. The post-save signal refreshes only
non-XC accounts on create (`apps/m3u/signals.py:19-20`); `create` itself runs only
`refresh_categories` (`apps/m3u/api_views.py:141-144`); `refresh_vod_content` is queued by the
scheduled or manual M3U refresh (`apps/m3u/tasks.py:4009-4014`) or by `POST .../refresh-vod/`. In the
meantime the UI's group-filter modal, which lists only categories that carry a relation to the
account (`VODCategoryFilter.jsx:30-55`), fetches exactly this endpoint when it opens for an XC account
with VOD (`M3UGroupFilter.jsx:54-64` → `useVODStore.fetchCategories` → `api.getVODCategories`,
`frontend/src/api.js:3679-3686`). The list's write is what made `Uncategorized` appear in that modal
for a new account. Deleting it without a replacement would make the row appear only after the first
refresh.

Three smaller gaps the list also covered, which this plan leaves to the next refresh: `enable_vod` set
through the raw `custom_properties` payload rather than the top-level flag (the serializer merges it,
`apps/m3u/serializers.py:283-289`, but `update` only watches `request.data["enable_vod"]`,
`:195`); an XC account with `enable_vod` created or edited outside `M3UAccountViewSet` altogether
(a Django shell, a plugin writing the ORM, a fixture), which neither `create` nor `update` sees; and
an account whose refreshes abort on empty categories (`refresh_movies` never runs).

### The issue's diagnosis needs one correction

The issue says the D-4 wait "hung ... because each poll of the endpoint added an 'Uncategorized'
row", and that after the fix "the e2e pin can go back to an exact count". Two parts of that are not
what the code does:

- No poll added a row after the first. `get_or_create` plus `unique_together` means the list adds at
  most two relations per account, ever.
- **The account's `m3u_account`-filtered answer is five rows with or without the fix**, never three:
  `refresh_movies` and `refresh_series` create the same two `Uncategorized` relations for the account
  being refreshed, and the spec's own `POST refresh-vod/` runs exactly that. D-4's exact-three wait
  could never have held.

So the e2e pin goes back to an **exact** answer — the account's five `(category_type, name)` pairs —
and it does **not** discriminate the fix: it passes on the seed too (Appendix F's comment says so).
The discrimination lives in the backend pin (Appendix D), which fails on the seed with four
`INSERT`s.

### Rulings (where the issue was silent)

- **D1. Relation creation moves to one helper, `ensure_uncategorized_relations(account)` in
  `apps/vod/tasks.py`, called from `M3UAccountViewSet.create` (new) and `.update` (replacing its
  inline copy).** Why these two call sites: they are where VOD is turned on, which is the moment the
  UI needs the row (above). Why not the refresh alone: it would regress the new-account modal, and it
  would make G9 row 5 racy — that test waits for its provider category's relation, which
  `refresh_categories` writes, and then reads the `Uncategorized` relations, which `refresh_movies`
  writes later and `refresh_series` later still, after every movie is processed; today the read
  itself papers over that gap. With the helper in `create`, both relations exist from the moment the
  account does. Why not a management command: nothing about this is an operator step; the row is
  needed at the moment VOD is enabled. Why `apps/vod/tasks.py`: it is the module that already owns the
  refresh's `Uncategorized` handling, and `apps/m3u/api_views.py` already imports from it lazily
  (`:142`, `:242`), so no new import edge appears between the apps.
- **D2. The helper gates itself on the stored account: XC and `custom_properties["enable_vod"]`.**
  `create` therefore calls it for every XC account, before either provider round-trip, so the
  relations exist even when the provider fails (`create` runs both round-trips with no `try`;
  recorded at `docs/superpowers/specs/2026-08-30-e2e-vod-series-design.md:278-282`). The gate reads
  the value the serializer stored as a boolean (`apps/m3u/serializers.py:355` and `:366` on create,
  `:271` and `:291-292` on update), not `request.data`. The gate is deliberately narrower than the old
  list's, which also required `is_active=True` (`apps/vod/api_views.py:665-668`): the helper has no
  `is_active` check, so an inactive XC account created with VOD on, or switched to it, gets its
  relations at that moment rather than on activation. That is acceptable because the relations are
  inert until a refresh reads them, a refresh runs only for an active account (`refresh_vod_content`
  fetches the account with `is_active=True`, `apps/vod/tasks.py:58`), and having the row present
  before activation is what the group-filter modal wants anyway.
- **D3. A new series relation's `enabled` comes from `auto_enable_new_groups_series`.** That is the
  key `batch_create_categories` (`apps/vod/tasks.py:312-315`) and `refresh_series` (`:251`) use,
  and the one the modal's series tab edits (`M3UGroupFilter.jsx:165-173`,
  `autoEnableNewGroupsSeries`). The list and `update` used `auto_enable_new_groups_vod` for both. **Behaviour change**, visible only when the two flags
  differ on an account that gets its relations from `create`/`update`; an existing relation is never
  changed (`get_or_create`'s `defaults` apply on insert only).
- **D4. `update` reads the account back (`instance.refresh_from_db()`) before calling the helper.**
  `instance` is fetched before `super().update()` (`apps/m3u/api_views.py:150`), and DRF's
  `update` fetches its own copy, so `instance.custom_properties` are the pre-request ones. That is a
  recorded defect (`docs/superpowers/specs/2026-08-30-e2e-vod-series-design.md:283-286`: a PATCH
  carrying `enable_vod: true` and `auto_enable_new_groups_vod: false` creates the relations with the
  old flag). With D2's gate it matters more: measured, without the read-back the helper sees
  `enable_vod: False` and creates nothing. Appendix E's third test pins it.
- **D5. `refresh_movies` and `refresh_series` keep their own `get_or_create`.** They need the returned
  category and relation objects for `relations` and `categories_by_provider` (`:212-216`,
  `:267-271`) and log on creation. Folding them into the helper is a refactor this issue does not
  need.
- **D6. No data migration and no management command.** (a) Any install where the VOD UI or the group
  filter was ever opened already has both relations for every active account that had VOD on at the
  time, because the list ran. (b) The relation's only functional consumer is the refresh, which creates it
  before use: `refresh_movies` puts it into `relations` before any movie is processed, and movies are
  routed to `Uncategorized` only inside a refresh (`apps/vod/tasks.py:455-465`, `:827-837`). (c) Any
  account still missing one gets it from its next VOD refresh, which every scheduled M3U refresh
  queues for a VOD-enabled XC account (`apps/m3u/tasks.py:4009-4014`). The only visible gap is the
  `Uncategorized` row missing from that account's group-filter modal until then. A `RunPython` over
  `M3UAccount.custom_properties` would add a migration with no meaningful reverse to the 16 that
  already have none (`CLAUDE.md` § Known defects), to close a cosmetic, self-healing gap.
- **D7. The e2e rule "never assert that an account lacks an `Uncategorized` relation" stays.** Its old
  reason was the list writing for every account. Its new reason: creating the account with VOD on,
  the update that turns VOD on and every refresh each create both relations, so absence is never a
  stable state for an `enable_vod` XC account. Appendix G rewrites the two comments that state the old
  reason, and Appendix H the README paragraph.
- **D8. The pure-read pin asserts zero write statements, not an exact query count.** Measured with
  `CaptureQueriesContext`, filtering captured SQL whose first word is `INSERT`, `UPDATE` or `DELETE`.
  An `assertNumQueries` would pin the read's own shape (serializer prefetches, filter joins), which is
  not the property and would move on unrelated edits. `apps/proxy/tests/test_tune_path_query_ledger.py`
  is the house idiom for a query ledger; it pins an exact multiset because that hot path's reads are
  the property. Here the property is "no write". The repo's recorded lessons, applied:
  - *Warm state hides a query*: the request under test is the test's first, with no `Uncategorized`
    row in the database, which is exactly the state in which the old list wrote the most.
  - *The tautological oracle*: the expected value is the literal `[]`, not computed by the code under
    test, and two independent ORM `exists()` checks back it.
  - *A pin that supplies the default pins nothing*: the account carries the non-default
    `enable_vod: True` and is XC and active, every condition the old list wrote under. Measured: the
    old list writes four rows with it. Without it, only the two category rows would be written (read
    from `:652-662`, not measured), and the relation half of the write would go unobserved.

### Frontend

No change. `grep -rn "Uncategorized\|vod/categories" frontend/src` finds only
`frontend/src/api.js:3681` (the GET). The five call sites of `fetchCategories`
(`M3UGroupFilter.jsx:62`, `M3U.jsx:181` and `:511`, `M3URefreshNotification.jsx:213`,
`pages/VODs.jsx:106`) only read. The one behaviour they relied on, `Uncategorized` showing in the
modal for a new XC account with VOD, is preserved by D1.

---

## Metrics dashboard

**No `metrics/curated/` edit.** #490 has no `defects.yml` row
(`grep -cE "issue: 490[,} ]" metrics/curated/defects.yml` prints `0` at seed), it is not a `CLAUDE.md`
§ Known defects bullet, and no `test.fail()` pins it. `docs/agents/metrics.md` § `defects.yml` asks for
an update only when a PR closes a ledger issue or adds a pin for one. No milestone kind applies. So
`python -m metrics.build --validate-only` is not a step.

---

## PR: `fix/490-vod-category-list-pure-read`

- **Issue** #490 (planned here). The implementation PR's description carries its closing line.
- **Files** the nine in § Files this plan touches.
- **Backend labels**: `python3 scripts/ci_backend_test_labels.py <each changed path>` prints
  `["apps.m3u.tests", "apps.output.tests", "apps.vod.tests"]` at seed (`apps/vod/` is aliased to both
  `apps.vod.tests` and `apps.output.tests`; the e2e, README and COVERAGE paths route to no label).
- **E2E project**: `seeded`, the two touched specs, on a private stack (Task 4).
- **Size** S. **Upstreamable**: not assessed; upstream `dev` was not checked for this plan.

### Test modifications (Global constraint 4)

| Test | Before (seed) | After |
|---|---|---|
| `vod-ingest-fidelity.spec.ts` `'GET /api/vod/categories/ accepts an m3u_account filter'`, the `waitFor.resource` predicate | `(body) => expectedNames.every((n) => body.some((c) => c.name === n))` — the three `${prefix}` names present, anything else allowed | `(body) => JSON.stringify(rowsOf(body)) === JSON.stringify(expectedRows)` — exactly `movie:${prefix}-movies-a`, `movie:${prefix}-movies-b`, `movie:Uncategorized`, `series:${prefix}-shows`, `series:Uncategorized`; the waiter's `description` names the five; `timeoutMs` unchanged at `120_000` |
| same test, new assertion | — | `expect(rowsOf(categories), …).toEqual(expectedRows)` after the waiter, so a failure prints the diff rather than only the waiter's timeout |
| same test, the three `toBeDefined` loop, the per-row relation check and the decoy check | unchanged | unchanged |
| `vod-category-gating.spec.ts` G9 row 5 | assertions unchanged | assertions unchanged; three comments rewritten (Appendix G) |

No backend test changes. `apps.vod.tests.test_vod_category_account_filter` stays green unmodified: its
two XC accounts carry no `enable_vod`, so the old list never wrote for them.

### Task 0: occupancy, worktree, private container, baseline

- [ ] **Step 1. Occupancy.** Before creating anything, confirm nobody holds the names:

  ```bash
  docker ps -a --filter name=fix-490 --format '{{.Names}} {{.Status}}'
  ls -d /Users/dion/git/Dispatcharr/.worktrees/fix-490 && stat -f '%Sm %N' /Users/dion/git/Dispatcharr/.worktrees/fix-490
  ```

  Both must print nothing / "No such file". If either exists, check mtimes (`CLAUDE.md` § Repository
  and direction) and STOP rather than reuse.
- [ ] **Step 2. Worktree.**

  ```bash
  git -C /Users/dion/git/Dispatcharr fetch origin
  git -C /Users/dion/git/Dispatcharr worktree add -b fix/490-vod-category-list-pure-read /Users/dion/git/Dispatcharr/.worktrees/fix-490 origin/main
  ```

- [ ] **Step 3. The plan's appendices must still apply.** Extract them (§ Appendix extraction) to
  `X=<your scratchpad>/490`, then:

  ```bash
  cd "$WT" && for a in A B C D E F G H I; do git apply --check "$X/appendix-$a.diff" || echo "REFUSED $a"; done
  ```

  It must print nothing. Any `REFUSED` is a STOP (Global constraint 5).
- [ ] **Step 4. Private container and baseline.** Start `fix-490` (Global constraint 6), confirm the
  mount (`docker inspect fix-490 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'`
  shows `$WT -> /repo`), then per label: `docker exec fix-490 redis-cli flushall` and
  `T --keepdb <label>`. Expected at seed: `apps.vod.tests` **Ran 85 tests, OK**;
  `apps.output.tests` **Ran 121, OK**; `apps.m3u.tests` **Ran 245, OK**. If `main` has moved, record
  your own numbers; a red baseline is a STOP.

### Task 1: the tests first, red on the unfixed tree

- [ ] **Step 1.** `cd "$WT" && git apply "$X/appendix-D.diff" "$X/appendix-E.diff"`. Two new files,
  59 and 104 lines (`wc -l`).
- [ ] **Step 2.** Run them against the unfixed code:
  `T --keepdb apps.vod.tests.test_vod_category_list_pure_read apps.m3u.tests.test_vod_uncategorized_relations`.
  Expected, measured at seed: **Ran 4 tests, FAILED (failures=3)**:

  | Test | Failure at seed |
  |---|---|
  | `test_listing_categories_writes_no_row` | `AssertionError: Lists differ: ['INSERT INTO "vod_vodcategory" ("name", "[<n> chars]id"'] != []`, then `First list contains 4 additional elements.`, ending `: GET /api/vod/categories/ wrote to the database` (`<n>` varies with the timestamps) |
  | `test_creating_an_xc_account_with_vod_creates_both_relations_each_with_its_own_flag` | `AssertionError: {} != {'movie': False, 'series': True}` |
  | `test_enabling_vod_reads_the_flags_the_same_request_set` | `AssertionError: {'movie': True, 'series': True} != {'movie': False, 'series': False}` (the stale-instance defect, D4) |
  | `test_creating_an_xc_account_without_vod_creates_no_relation` | passes at seed; it guards D2's gate once `create` calls the helper for every XC account |

  Paste the three lines into the PR description's pin-flip table.

### Task 2: the fix, green

- [ ] **Step 1.** `cd "$WT" && git apply "$X/appendix-A.diff" "$X/appendix-B.diff" "$X/appendix-C.diff"`.
- [ ] **Step 2.** Same command as Task 1 Step 2. Expected: **Ran 4 tests, OK**.
- [ ] **Step 3.** `cd "$WT" && python3 scripts/check_credential_logging.py apps/vod/tasks.py apps/vod/api_views.py apps/m3u/api_views.py apps/vod/tests/test_vod_category_list_pure_read.py apps/m3u/tests/test_vod_uncategorized_relations.py; echo "rc=$?"`
  prints `rc=0` and nothing else (measured).
- [ ] **Step 4.** The old behaviour is gone.
  `awk '/^class VODCategoryViewSet/,/^class UnifiedContentViewSet/' apps/vod/api_views.py | grep -c "def list"`
  prints `0` (`1` at seed), and `grep -c "get_or_create" apps/vod/api_views.py` prints `0` (`4` at
  seed). Run both bare: `grep -c` exits 1 when it prints `0`, which here is the pass.

### Task 3: break-checks (each reverted before the next)

Each row makes one wrong edit, runs the named test, confirms the failure names the mechanism, then
reverts. A failure that is an `ImportError`, a `NameError`, or names a different mechanism is not a
pass (the "true positive for a false reason" lesson). After each revert,
`git -C "$WT" diff --stat` must show only the appendices' own changes.

| # | Wrong edit | Test | Expected failure (measured) |
|---|---|---|---|
| 1 | `cd "$WT" && git apply -R "$X/appendix-B.diff"` (restores the list override and its import) | `apps.vod.tests.test_vod_category_list_pure_read` | `AssertionError: Lists differ: ['INSERT INTO "vod_vodcategory" ("name", "[<n> chars]id"'] != []` / `First list contains 4 additional elements.` |
| 2 | delete the line `            ensure_uncategorized_relations(M3UAccount.objects.get(pk=account_id))` from `apps/m3u/api_views.py` | `apps.m3u.tests.test_vod_uncategorized_relations` | `test_creating_an_xc_account_with_vod_…`: `AssertionError: {} != {'movie': False, 'series': True}` |
| 3 | in `apps/vod/tasks.py` change `("series", "auto_enable_new_groups_series"),` to `("series", "auto_enable_new_groups_vod"),` | same | `test_creating_an_xc_account_with_vod_…`: `AssertionError: {'movie': False, 'series': False} != {'movie': False, 'series': True}` |
| 4 | delete the line `            instance.refresh_from_db()` from `apps/m3u/api_views.py` | same | `test_enabling_vod_reads_the_flags_the_same_request_set`: `AssertionError: {} != {'movie': False, 'series': False}` (the stale instance says `enable_vod: False`, so D2's gate returns) |
| 5 | in `apps/vod/tasks.py` replace `    if account.account_type != M3UAccount.Types.XC or not custom_props.get("enable_vod", False):` with `    if account.account_type != M3UAccount.Types.XC:` | same | `test_creating_an_xc_account_without_vod_creates_no_relation`: `AssertionError: {'movie': True, 'series': True} != {}` |

Make edits 2-5 with a guarded one-shot replace, so a drifted anchor fails loudly instead of editing
nothing. For example, row 4:

```bash
cd "$WT" && python3 -c "
import pathlib; p = pathlib.Path('apps/m3u/api_views.py'); s = p.read_text()
old = '            instance.refresh_from_db()\n'
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, ''))"
```

Revert rows 2-5 with `git -C "$WT" checkout -- apps/m3u/api_views.py apps/vod/tasks.py` followed by
`git -C "$WT" apply "$X/appendix-A.diff" "$X/appendix-C.diff"`; revert row 1 with
`git -C "$WT" apply "$X/appendix-B.diff"`. Paste the five failure lines into the PR description.

### Task 4: e2e and docs

- [ ] **Step 1.** `cd "$WT" && git apply "$X/appendix-F.diff" "$X/appendix-G.diff" "$X/appendix-H.diff" "$X/appendix-I.diff"`.
- [ ] **Step 2.** `cd "$WT/e2e" && npm ci && npx tsc --noEmit; echo "tsc=$?"` prints `tsc=0`
  (measured). Then `npx playwright test --project=guards`: **50 passed** at seed plus these edits
  (measured). Both touched tests keep exactly one `@contract` tag (ADR 0002).
- [ ] **Step 3. Seeded run on a private stack** (`e2e/README.md` § Running a second stack; private
  image and private provider, because product code changed and the shared image is stale):

  ```bash
  cd "$WT" && export DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-f490 \
         DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-f490-data \
         DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-f490-net \
         DISPATCHARR_E2E_PORT=39490 \
         DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-f490:local \
         DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-f490 \
         DISPATCHARR_E2E_UPSTREAM_PORT=39491 \
         DISPATCHARR_E2E_UPSTREAM_IMAGE=dispatcharr-e2e-upstream-f490:local \
         E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:39491 \
         E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-f490:8080 \
    && ./scripts/e2e_up.sh
  cd "$WT/e2e" && npx playwright install chromium \
    && E2E_BASE_URL=http://localhost:39490 npx playwright test --project=seeded \
         tests/seeded/vod-ingest-fidelity.spec.ts tests/seeded/vod-category-gating.spec.ts
  ```

  Expected: every test in both files passes. **Not run by the planner** (see § What the planner did
  not verify). If the `m3u_account`-filter test times out, its waiter prints the last observed body:
  read which of the five rows is missing or extra before touching anything, and never loosen the
  predicate (Global constraint 4). Tear the stack down by name, never with `--down`/`--reset`:
  `docker rm -f dispatcharr-e2e-f490 e2e-upstream-f490 && docker volume rm dispatcharr-e2e-f490-data && docker network rm dispatcharr-e2e-f490-net`.

### Task 5: labels, commit, PR

- [ ] **Step 1.** Per label, `docker exec fix-490 redis-cli flushall`, then `T --noinput <label>`
  **without `--keepdb`** and once with it. Expected (measured at seed + this plan):
  `apps.vod.tests` **Ran 86, OK**; `apps.output.tests` **Ran 121, OK**; `apps.m3u.tests`
  **Ran 248, OK**.
- [ ] **Step 2.** `git -C "$WT" status --porcelain` lists exactly the nine files. Stage them in one
  Bash call (`git -C "$WT" add <the nine paths>`); write the message with the Write tool; commit in a
  separate call with `git -C "$WT" commit -F <file>`. Suggested message:
  `fix(vod): GET /api/vod/categories/ is a pure read; turning VOD on creates the Uncategorized relations (#490)`,
  a body summarising D1-D4, and the attribution line from your session. No closing keyword in the
  commit message (Global constraint 9). The commit gate runs the three labels in the shared
  container and will only **warn** on the mount mismatch; that warning is not a result — Step 1 is.
- [ ] **Step 3.** `git -C "$WT" push -u origin fix/490-vod-category-list-pure-read`, then
  `gh pr create --repo D10Scot/Dispatcharr --draft --base main --title "<the commit subject>" --body-file <file>`
  with the draft below, its placeholders filled.
- [ ] **Step 4.** Remove the private test container and its volume:
  `docker rm -f fix-490 && docker volume rm fix-490-db`.

### PR description draft

> **fix(vod): GET /api/vod/categories/ is a pure read; turning VOD on creates the Uncategorized relations (#490)**
>
> `VODCategoryViewSet.list()` created the movie and series `Uncategorized` categories, and a relation
> to each for every active XC account with VOD enabled, on every call. Any Standard-level user's read
> wrote rows attached to every such account on the instance (the action is `IsStandardUser`; a
> Streamer gets 403 and never reached the write). The override is gone and the list is a pure read.
>
> The write was papering over one real gap: an XC account created with VOD on got no `Uncategorized`
> relation until its first full VOD refresh, which the create does not queue, and the group-filter
> modal fetches this very endpoint. A new helper, `apps.vod.tasks.ensure_uncategorized_relations`,
> now runs where VOD is turned on: in `M3UAccountViewSet.create` for every XC account (it is a no-op
> unless the stored `enable_vod` is set) and in `.update` in place of its inline copy. The refresh
> still creates them too.
>
> Two behaviour changes ride along, both pinned:
> - a new series relation takes `auto_enable_new_groups_series`, as `batch_create_categories` and
>   `refresh_series` already do (the list and `update` used `auto_enable_new_groups_vod` for both);
> - `update` reads the account back before creating the relations, so a PATCH that turns VOD on and
>   sets the auto-enable flags uses the flags it sets (a stale-instance bug recorded in the G9 spec).
>
> No migration: installs where the VOD UI was ever opened already have the rows, and any account
> still missing one gets it from its next VOD refresh.
>
> The issue expected the e2e `m3u_account`-filter pin to go back to exactly three rows. It is five:
> the refresh creates the account's two `Uncategorized` relations as well, so three never held, with
> or without this change. The pin now asserts the exact five and says it does not discriminate this
> fix; `apps.vod.tests.test_vod_category_list_pure_read` does.
>
> ## Pin-flip table
>
> | Test | Before (base `<base sha>`) | After |
> |---|---|---|
> | `test_listing_categories_writes_no_row` | `<Task 1 line>` | passes |
> | `test_creating_an_xc_account_with_vod_creates_both_relations_each_with_its_own_flag` | `<Task 1 line>` | passes |
> | `test_enabling_vod_reads_the_flags_the_same_request_set` | `<Task 1 line>` | passes |
>
> ## Break-check table
>
> | Edit | Test | Verbatim failure |
> |---|---|---|
> | <Task 3, five rows> | | |
>
> ## Test modifications
>
> `vod-ingest-fidelity.spec.ts`: the `m3u_account`-filter waiter's predicate goes from "the three
> `${prefix}` names are present" to "exactly these five `(category_type, name)` pairs", plus one
> `toEqual` on the same set; timeout unchanged. `vod-category-gating.spec.ts`: comments only.
> `e2e/README.md` and `e2e/COVERAGE.md` record the retired hazard.
>
> ## Tests run
>
> - `apps.vod.tests` <n> OK, `apps.output.tests` <n> OK, `apps.m3u.tests` <n> OK, each once without
>   `--keepdb`, in private container `fix-490`.
> - `cd e2e && npx tsc --noEmit` clean; `--project=guards` <n> passed.
> - `--project=seeded` on the two touched specs, private stack: <result>.
> - `scripts/check_credential_logging.py` clean on the five Python files.
>
> <closing line for issue 490, written here by the implementer; this plan does not spell it>
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## What the planner verified, and what it did not

Verified in private container `plan-490` (mounted at the planner's worktree, seed `93d1e424` plus the
appendices, then reverted): the seed baselines (85 / 121 / 245, OK); the four new tests red at seed as
tabled (3 failures) and green with the fix; all five break-checks with the failure lines quoted; the
three labels green with the fix, once without `--keepdb` (86 / 121 / 248, OK); the credential check;
`scripts/ci_backend_test_labels.py`'s routing; `e2e` `tsc --noEmit` and `--project=guards` (50
passed); and every appendix extracted from this file by § Appendix extraction and accepted by
`git apply --check` at `93d1e424`, then applied in Task 1/Task 2 order: D and E alone gave the three
tabled failures, A to I together gave **Ran 4 tests, OK** and a clean `tsc`, and `git apply -R` of
Appendix B reproduced break-check 1.

**Not verified: the `seeded` e2e run** of the two touched specs. It needs a private image build and
stack, which the planner did not bring up. The five-row claim rests on reading
`refresh_movies`/`refresh_series` (`apps/vod/tasks.py:187-216`, `:242-271`), `unique_together` at
`apps/vod/models.py:333`, and `seedCatalogue`'s declared categories
(`e2e/tests/seeded/vod-ingest-fidelity.spec.ts:50-54`). Task 4 Step 3 is where it is measured.

---

## Appendix extraction

Each appendix below is a unified diff against `93d1e424`, headed `### Appendix <letter>`. Extract
all nine to `$X`:

```bash
PLAN="$WT/docs/superpowers/plans/2026-09-25-fix-490-vod-category-list-pure-read.md"
test -f "$PLAN" || { PLAN="<your scratchpad>/490-plan.md"; git -C "$WT" show "origin/docs/plan-490-vod-category-pure-read:docs/superpowers/plans/2026-09-25-fix-490-vod-category-list-pure-read.md" > "$PLAN"; }
X="<your scratchpad>/490"
python3 - "$PLAN" "$X" <<'PY'
import pathlib, re, sys
plan = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
pat = re.compile(r"^### Appendix ([A-I]) [^\n]*\n\n```diff\n(.*?)^```$", re.S | re.M)
found = pat.findall(plan)
assert [l for l, _ in found] == list("ABCDEFGHI"), [l for l, _ in found]
for letter, body in found:
    (out / f"appendix-{letter}.diff").write_text(body)
    print(letter, len(body.splitlines()))
PY
```

It must print nine lines: `A 49`, `B 73`, `C 70`, `D 65`, `E 110`, `F 42`, `G 47`, `H 25`, `I 12`.

### Appendix A — `apps/vod/tasks.py`: the helper

```diff
diff --git a/apps/vod/tasks.py b/apps/vod/tasks.py
index 07d92c75..58ee153e 100644
--- a/apps/vod/tasks.py
+++ b/apps/vod/tasks.py
@@ -27,6 +27,44 @@ def _empty_categories_should_abort(categories_data, account, category_type):
     ).exclude(category__name='Uncategorized').exists()
 
 
+def ensure_uncategorized_relations(account):
+    """Give an XC account with VOD enabled its two "Uncategorized" relations.
+
+    Creates the movie and series "Uncategorized" VODCategory rows if they are
+    missing, and this account's M3UVODCategoryRelation to each, so the
+    category shows in the account's group filter before the first VOD
+    refresh has run. Idempotent: an existing relation is left exactly as it
+    is, so a user's enabled/disabled choice survives. A new relation takes
+    its enabled flag from the account's auto-enable preference for that
+    type, the same key batch_create_categories and refresh_movies /
+    refresh_series read. Does nothing for a non-XC account or one without
+    custom_properties["enable_vod"].
+
+    Called from M3UAccountViewSet.create and .update. It used to run from
+    VODCategoryViewSet.list, on every GET and for every account (#490).
+    """
+    custom_props = account.custom_properties or {}
+    if account.account_type != M3UAccount.Types.XC or not custom_props.get("enable_vod", False):
+        return
+
+    for category_type, auto_enable_key in (
+        ("movie", "auto_enable_new_groups_vod"),
+        ("series", "auto_enable_new_groups_series"),
+    ):
+        category, _ = VODCategory.objects.get_or_create(
+            name="Uncategorized",
+            category_type=category_type,
+        )
+        M3UVODCategoryRelation.objects.get_or_create(
+            category=category,
+            m3u_account=account,
+            defaults={
+                "enabled": custom_props.get(auto_enable_key, True),
+                "custom_properties": {},
+            },
+        )
+
+
 def lookup_by_name_year(model, name_year_pairs):
     """Return {(name, year): row} for rows without TMDB/IMDB IDs.
 
```

### Appendix B — `apps/vod/api_views.py`: the list override deleted

```diff
diff --git a/apps/vod/api_views.py b/apps/vod/api_views.py
index ea3f3c0f..8c42e1c3 100644
--- a/apps/vod/api_views.py
+++ b/apps/vod/api_views.py
@@ -15,7 +15,7 @@ from apps.accounts.permissions import (
 )
 from .models import (
     Series, VODCategory, Movie, Episode, VODLogo,
-    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
+    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation
 )
 from .serializers import (
     MovieSerializer,
@@ -644,59 +644,6 @@ class VODCategoryViewSet(viewsets.ReadOnlyModelViewSet):
         except KeyError:
             return [Authenticated()]
 
-    def list(self, request, *args, **kwargs):
-        """Override list to ensure Uncategorized categories and relations exist for all XC accounts with VOD enabled"""
-        from apps.m3u.models import M3UAccount
-
-        # Ensure Uncategorized categories exist
-        movie_category, _ = VODCategory.objects.get_or_create(
-            name="Uncategorized",
-            category_type="movie",
-            defaults={}
-        )
-
-        series_category, _ = VODCategory.objects.get_or_create(
-            name="Uncategorized",
-            category_type="series",
-            defaults={}
-        )
-
-        # Get all active XC accounts with VOD enabled
-        xc_accounts = M3UAccount.objects.filter(
-            account_type=M3UAccount.Types.XC,
-            is_active=True
-        )
-
-        for account in xc_accounts:
-            if account.custom_properties:
-                custom_props = account.custom_properties or {}
-                vod_enabled = custom_props.get("enable_vod", False)
-
-                if vod_enabled:
-                    # Ensure relations exist for this account
-                    auto_enable_new = custom_props.get("auto_enable_new_groups_vod", True)
-
-                    M3UVODCategoryRelation.objects.get_or_create(
-                        category=movie_category,
-                        m3u_account=account,
-                        defaults={
-                            'enabled': auto_enable_new,
-                            'custom_properties': {}
-                        }
-                    )
-
-                    M3UVODCategoryRelation.objects.get_or_create(
-                        category=series_category,
-                        m3u_account=account,
-                        defaults={
-                            'enabled': auto_enable_new,
-                            'custom_properties': {}
-                        }
-                    )
-
-        # Now proceed with normal list operation
-        return super().list(request, *args, **kwargs)
-
 
 class UnifiedContentViewSet(viewsets.ReadOnlyModelViewSet):
     """ViewSet that combines Movies and Series for unified 'All' view"""
```

### Appendix C — `apps/m3u/api_views.py`: create and update call the helper

```diff
diff --git a/apps/m3u/api_views.py b/apps/m3u/api_views.py
index 26eaf342..86029d10 100644
--- a/apps/m3u/api_views.py
+++ b/apps/m3u/api_views.py
@@ -134,6 +134,12 @@ class M3UAccountViewSet(viewsets.ModelViewSet):
         })
 
         if account_type == M3UAccount.Types.XC:
+            from apps.vod.tasks import ensure_uncategorized_relations
+
+            # Before either provider round-trip, so the relations exist even
+            # when the provider fails; a no-op unless VOD is enabled.
+            ensure_uncategorized_relations(M3UAccount.objects.get(pk=account_id))
+
             refresh_m3u_groups(account_id)
 
             # Check if VOD is enabled
@@ -199,44 +205,14 @@ class M3UAccountViewSet(viewsets.ModelViewSet):
             and not old_vod_enabled
             and new_vod_enabled
         ):
-            # Create Uncategorized categories immediately so they're available in the UI
-            from apps.vod.models import VODCategory, M3UVODCategoryRelation
-
-            # Create movie Uncategorized category
-            movie_category, _ = VODCategory.objects.get_or_create(
-                name="Uncategorized",
-                category_type="movie",
-                defaults={}
-            )
-
-            # Create series Uncategorized category
-            series_category, _ = VODCategory.objects.get_or_create(
-                name="Uncategorized",
-                category_type="series",
-                defaults={}
-            )
-
-            # Create relations for both categories (disabled by default until first refresh)
-            account_custom_props = instance.custom_properties or {}
-            auto_enable_new = account_custom_props.get("auto_enable_new_groups_vod", True)
-
-            M3UVODCategoryRelation.objects.get_or_create(
-                category=movie_category,
-                m3u_account=instance,
-                defaults={
-                    'enabled': auto_enable_new,
-                    'custom_properties': {}
-                }
-            )
-
-            M3UVODCategoryRelation.objects.get_or_create(
-                category=series_category,
-                m3u_account=instance,
-                defaults={
-                    'enabled': auto_enable_new,
-                    'custom_properties': {}
-                }
-            )
+            # Create the Uncategorized relations now so they show in the
+            # account's group filter before the refresh below has run. Read
+            # the account back first: `instance` predates super().update(),
+            # so its custom_properties are the pre-request ones.
+            from apps.vod.tasks import ensure_uncategorized_relations
+
+            instance.refresh_from_db()
+            ensure_uncategorized_relations(instance)
 
             # Trigger full VOD refresh
             from apps.vod.tasks import refresh_vod_content
```

### Appendix D — `apps/vod/tests/test_vod_category_list_pure_read.py` (new)

```diff
diff --git a/apps/vod/tests/test_vod_category_list_pure_read.py b/apps/vod/tests/test_vod_category_list_pure_read.py
new file mode 100644
index 00000000..09dd540c
--- /dev/null
+++ b/apps/vod/tests/test_vod_category_list_pure_read.py
@@ -0,0 +1,59 @@
+"""GET /api/vod/categories/ is a pure read (#490).
+
+VODCategoryViewSet.list() used to get_or_create the movie and series
+"Uncategorized" categories and, for every active XC account with
+custom_properties["enable_vod"], that account's relation to each: on every
+GET, for any caller the list admits. Those rows are now created where VOD is
+turned on for an account (M3UAccountViewSet.create and .update, through
+apps.vod.tasks.ensure_uncategorized_relations) and on every VOD refresh
+(refresh_movies and refresh_series). Listing writes nothing.
+"""
+
+from django.contrib.auth import get_user_model
+from django.db import connection
+from django.test import TestCase
+from django.test.utils import CaptureQueriesContext
+from rest_framework.test import APIClient
+
+from apps.m3u.models import M3UAccount
+from apps.vod.models import M3UVODCategoryRelation, VODCategory
+
+User = get_user_model()
+
+_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE")
+
+
+class VodCategoryListIsAPureReadTests(TestCase):
+    def setUp(self):
+        # Standard is the lowest level the list admits
+        # (permission_classes_by_action["list"] is IsStandardUser).
+        user = User.objects.create_user(username="vodcatstandard", password="x")
+        user.user_level = User.UserLevel.STANDARD
+        user.save()
+        self.client = APIClient()
+        self.client.force_authenticate(user=user)
+        # Every condition the old list() wrote under: an XC account, active,
+        # with enable_vod set. enable_vod is False unless set, so a test
+        # that left it out would pass with or without the write.
+        self.account = M3UAccount.objects.create(
+            name="vod-on",
+            server_url="http://vod-on.example",
+            account_type=M3UAccount.Types.XC,
+            is_active=True,
+            custom_properties={"enable_vod": True},
+        )
+
+    def test_listing_categories_writes_no_row(self):
+        with CaptureQueriesContext(connection) as ctx:
+            res = self.client.get("/api/vod/categories/")
+        self.assertEqual(res.status_code, 200)
+        writes = [
+            q["sql"]
+            for q in ctx.captured_queries
+            if q["sql"].lstrip().upper().startswith(_WRITE_VERBS)
+        ]
+        self.assertEqual(writes, [], "GET /api/vod/categories/ wrote to the database")
+        self.assertFalse(VODCategory.objects.filter(name="Uncategorized").exists())
+        self.assertFalse(
+            M3UVODCategoryRelation.objects.filter(m3u_account=self.account).exists()
+        )
```

### Appendix E — `apps/m3u/tests/test_vod_uncategorized_relations.py` (new)

```diff
diff --git a/apps/m3u/tests/test_vod_uncategorized_relations.py b/apps/m3u/tests/test_vod_uncategorized_relations.py
new file mode 100644
index 00000000..b1118a62
--- /dev/null
+++ b/apps/m3u/tests/test_vod_uncategorized_relations.py
@@ -0,0 +1,104 @@
+"""An XC account's "Uncategorized" VOD relations are created where VOD is turned on (#490).
+
+They used to be created by GET /api/vod/categories/, for every enable_vod XC
+account on every call. They are now created by M3UAccountViewSet.create and
+.update through apps.vod.tasks.ensure_uncategorized_relations, and still by
+every VOD refresh. Each new relation takes its enabled flag from its own
+type's auto-enable key: auto_enable_new_groups_vod for movies,
+auto_enable_new_groups_series for series, as batch_create_categories,
+refresh_movies and refresh_series already do.
+"""
+
+from unittest.mock import patch
+
+from django.contrib.auth import get_user_model
+from django.test import TestCase
+from rest_framework.test import APIClient
+
+from apps.m3u.models import M3UAccount
+from apps.vod.models import M3UVODCategoryRelation
+
+User = get_user_model()
+
+
+class VodUncategorizedRelationsTests(TestCase):
+    def setUp(self):
+        admin = User.objects.create_user(username="vodrelsadmin", password="x")
+        admin.user_level = 10
+        admin.save()
+        self.client = APIClient()
+        self.client.force_authenticate(user=admin)
+
+    def _uncategorized(self, account_id):
+        """{category_type: enabled} for the account's Uncategorized relations."""
+        return {
+            rel.category.category_type: rel.enabled
+            for rel in M3UVODCategoryRelation.objects.filter(
+                m3u_account_id=account_id, category__name="Uncategorized"
+            ).select_related("category")
+        }
+
+    def _create_xc(self, **fields):
+        body = {
+            "name": "xc-vod",
+            "server_url": "http://xc-vod.example",
+            "account_type": "XC",
+            "username": "u",
+            "password": "p",
+            **fields,
+        }
+        res = self.client.post("/api/m3u/accounts/", body, format="json")
+        self.assertEqual(res.status_code, 201, res.content)
+        return res.data["id"]
+
+    # The two provider round-trips create() makes inline for an XC account.
+    @patch("apps.vod.tasks.refresh_categories")
+    @patch("apps.m3u.api_views.refresh_m3u_groups")
+    def test_creating_an_xc_account_with_vod_creates_both_relations_each_with_its_own_flag(
+        self, _groups, _categories
+    ):
+        # The two flags differ, and neither is the default for both, so a
+        # helper reading one key for both types fails here.
+        account_id = self._create_xc(
+            enable_vod=True,
+            auto_enable_new_groups_vod=False,
+            auto_enable_new_groups_series=True,
+        )
+        self.assertEqual(
+            self._uncategorized(account_id), {"movie": False, "series": True}
+        )
+
+    @patch("apps.vod.tasks.refresh_categories")
+    @patch("apps.m3u.api_views.refresh_m3u_groups")
+    def test_creating_an_xc_account_without_vod_creates_no_relation(
+        self, _groups, _categories
+    ):
+        account_id = self._create_xc(enable_vod=False)
+        self.assertEqual(self._uncategorized(account_id), {})
+
+    @patch("apps.vod.tasks.refresh_vod_content")
+    def test_enabling_vod_reads_the_flags_the_same_request_set(self, _refresh):
+        # The PATCH that turns VOD on also sets both flags False. The helper
+        # must see the account as this request left it: the pre-update
+        # instance still says enable_vod=False and carries neither flag
+        # (absent, so True by default).
+        account = M3UAccount.objects.create(
+            name="xc-later",
+            server_url="http://xc-later.example",
+            account_type=M3UAccount.Types.XC,
+            is_active=True,
+            custom_properties={"enable_vod": False},
+        )
+        res = self.client.patch(
+            f"/api/m3u/accounts/{account.id}/",
+            {
+                "enable_vod": True,
+                "auto_enable_new_groups_vod": False,
+                "auto_enable_new_groups_series": False,
+            },
+            format="json",
+        )
+        self.assertEqual(res.status_code, 200, res.content)
+        self.assertEqual(
+            self._uncategorized(account.id), {"movie": False, "series": False}
+        )
```

### Appendix F — `e2e/tests/seeded/vod-ingest-fidelity.spec.ts`: the exact five

```diff
diff --git a/e2e/tests/seeded/vod-ingest-fidelity.spec.ts b/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
index 03145c99..f076814b 100644
--- a/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
+++ b/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
@@ -336,18 +336,29 @@ test('GET /api/vod/categories/ accepts an m3u_account filter', { tag: '@contract
   // filter is scoping correctly or not. Wait for the three ${prefix}
   // categories the category-rows test above declares, the same way it does,
   // but through the m3u_account filter instead of name — that is the
-  // property under test. Not an exact-length predicate: VODCategoryViewSet.list()
-  // (apps/vod/api_views.py) also get_or_creates a movie and a series
-  // "Uncategorized" category and relation for every active XC account with
-  // VOD enabled, including this one, on every call to this same endpoint —
-  // so a correctly-scoped answer for this account is these three plus up to
-  // two Uncategorized rows, never exactly three.
+  // property under test. An exact set of five, not three: the answer also
+  // carries this account's own movie and series "Uncategorized" relations,
+  // which M3UAccountViewSet.create gives every XC account created with VOD
+  // on (apps.vod.tasks.ensure_uncategorized_relations) and every VOD refresh
+  // keeps (refresh_movies / refresh_series). The same five came back before
+  // #490, when VODCategoryViewSet.list() also get_or_created them on every
+  // call; that the list no longer writes is pinned by
+  // apps.vod.tests.test_vod_category_list_pure_read, not here.
   const expectedNames = [`${prefix}-movies-a`, `${prefix}-movies-b`, `${prefix}-shows`];
+  const expectedRows = [
+    `movie:${prefix}-movies-a`,
+    `movie:${prefix}-movies-b`,
+    'movie:Uncategorized',
+    `series:${prefix}-shows`,
+    'series:Uncategorized',
+  ].sort();
+  const rowsOf = (body: VodCategory[]) => body.map((c) => `${c.category_type}:${c.name}`).sort();
   const categories = await waitFor.resource<VodCategory[]>(
     url,
-    (body) => expectedNames.every((n) => body.some((c) => c.name === n)),
-    { description: `all 3 ${prefix} categories via the m3u_account filter`, timeoutMs: 120_000 }
+    (body) => JSON.stringify(rowsOf(body)) === JSON.stringify(expectedRows),
+    { description: `exactly the 5 categories of account ${account.id} via the m3u_account filter`, timeoutMs: 120_000 }
   );
+  expect(rowsOf(categories), `account ${account.id}'s m3u_account-filtered categories`).toEqual(expectedRows);
 
   for (const name of expectedNames) {
     const category = categories.find((c) => c.name === name);
```

### Appendix G — `e2e/tests/seeded/vod-category-gating.spec.ts`: comments only

```diff
diff --git a/e2e/tests/seeded/vod-category-gating.spec.ts b/e2e/tests/seeded/vod-category-gating.spec.ts
index afe6bf9c..ba3ab6e9 100644
--- a/e2e/tests/seeded/vod-category-gating.spec.ts
+++ b/e2e/tests/seeded/vod-category-gating.spec.ts
@@ -268,8 +268,8 @@ test('an uncategorised movie or series falls back to the Uncategorized category,
 
   // Both auto-enable flags false: refresh_movies/refresh_series always
   // get_or_create the Uncategorized category AND relation on every refresh
-  // (apps/vod/tasks.py:183-210), with `enabled = auto_enable_new_groups_vod`
-  // / `_series`. With both false on this account, `enabled: false` below is
+  // (apps/vod/tasks.py), with `enabled = auto_enable_new_groups_vod` /
+  // `_series`. With both false on this account, `enabled: false` below is
   // a real assertion about THIS account's flags — not a coincidence of
   // whatever the defaults happen to be — which is the whole reason this test
   // sets them false rather than leaving the (true) defaults.
@@ -298,21 +298,21 @@ test('an uncategorised movie or series falls back to the Uncategorized category,
 
   const categories = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
 
-  // Hazard 1: `GET /api/vod/categories/` itself get_or_creates these two
-  // Uncategorized relations for every enable_vod XC account
-  // (`VODCategoryViewSet.list`, apps/vod/api_views.py:647), with
-  // `defaults={'enabled': auto_enable_new}` — so this assertion holds
-  // whether the refresh above created the relation or this very GET did.
-  // Nothing here claims the refresh was what created it.
+  // Hazard 1: the refresh is not the only writer of these two relations.
+  // `M3UAccountViewSet.create` already created both when the account above
+  // was created with `enable_vod` (apps.vod.tasks.ensure_uncategorized_relations,
+  // `enabled` from `auto_enable_new_groups_vod` / `_series`), and the
+  // refresh's get_or_create leaves an existing row as it is — so this
+  // assertion holds whichever wrote the relation. Nothing here claims the
+  // refresh was what created it. (Until #490, this very GET created them too.)
   const uncategorizedMovieCat = categories.find(
     (c) => c.name === 'Uncategorized' && c.category_type === 'movie'
   )!;
   expect(uncategorizedMovieCat).toBeTruthy();
   const movieRelation = uncategorizedMovieCat.m3u_accounts.find((r) => r.m3u_account === account.id)!;
-  // Hazard 2: never assert the ABSENCE of this relation for any account —
-  // any other worker's own `GET /api/vod/categories/` call would create one
-  // for its own account, but never for this one (the relation is scoped by
-  // m3u_account), so only presence is safe to assert here.
+  // Hazard 2: never assert the ABSENCE of this relation for any enable_vod
+  // XC account — account create, the update that turns VOD on and every VOD
+  // refresh each create one, so only presence is safe to assert here.
   expect(movieRelation).toBeTruthy();
   expect(movieRelation.enabled).toBe(false);
 
```

### Appendix H — `e2e/README.md`

```diff
diff --git a/e2e/README.md b/e2e/README.md
index c4580f5c..6d555745 100644
--- a/e2e/README.md
+++ b/e2e/README.md
@@ -359,12 +359,14 @@ applies to channels elsewhere in this harness. Scope every assertion by both `?m
 generated name; a fixed literal name will collide with another worker's or another test's catalogue
 on a shared instance.
 
-**`GET /api/vod/categories/` is unpaginated, and it writes rows on every call.** Its `list()`
-`get_or_create`s the two `Uncategorized` categories (movie and series) and their
-`M3UVODCategoryRelation` rows for *every* active `enable_vod` XC account on the instance — including
-other workers'. Locate your category with `find`, never a length or an index, and never assert that
-an account *lacks* an `Uncategorized` relation — another test's `GET` may have created it moments
-before yours ran.
+**`GET /api/vod/categories/` is unpaginated.** It has been a pure read since
+[#490](https://github.com/D10Scot/Dispatcharr/issues/490); until then its `list()` also
+`get_or_create`d the two `Uncategorized` categories and their `M3UVODCategoryRelation` rows for
+*every* active `enable_vod` XC account on every call. An unfiltered list still carries every other
+worker's categories, so locate yours with `find`, never a length or an index; `?m3u_account=<id>`
+scopes the answer to one account's relations exactly. Never assert that an `enable_vod` XC account
+*lacks* an `Uncategorized` relation: creating the account with VOD on, the update that turns VOD on
+and every VOD refresh each create both.
 
 **The four Lua scripts in `vod_proxy`'s stream counter are off limits.** They bypass the session
 metadata lock deliberately, as a real bug fix pinned by
```

### Appendix I — `e2e/COVERAGE.md`

```diff
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index a26b8591..aecb4ad7 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -96,6 +96,7 @@ resolve (see the G8/G10 Gap rows).
 | VOD | **Gap:** `not-found`/`auth-failure` have no effect on `/movie/<user>/<pass>/<id>.<ext>` or `/series/<user>/<pass>/<id>.<ext>` (G8 Task 7). Both routes call `serveVodAsset` directly and never reach `serveChannelStream` — the pipeline that gives `/live/` and both catch-up routes those two faults for free — so arming either against a VOD id is silently a no-op: `200 appliedTo: 0` from `/fault`, identical to a correct arm, and the asset still serves normally. This is the same shape as the method-gate row above, not a new one: both fixes land at the same `handleXc` seam that row already names, since neither VOD route is reached through `serveChannelStream` for the same reason neither has its method checked there. **Fixed by G9 Task 2** (`e2e-upstream` commit `dbbd8666`): both faults are now checked directly in `handleXc`'s `vodMatch` branch. Scenario-wide only — a `{ channel: n }` arm still does not reach a VOD route, because a VOD id is not a channel id | G9 | done |
 | VOD | **Known defect, elaborating the `range-unsupported` row above:** arming `range-unsupported` and requesting a mid-file `Range` through `/proxy/vod/movie/<uuid>` (G8 Task 10) produces a `206` with a `Content-Range` naming exactly the range the *client* asked for and a matching `Content-Length` — but the **bytes are wrong**. Verified byte-for-byte, not just by length: with a 125,585-byte asset and `Range: bytes=100-199`, the 100-byte body received was byte-identical to the file's bytes **0-99**, not 100-199, while the response claimed `Content-Range: bytes 100-199/125585`. Mechanism, confirmed in source: `stream_content_with_session` (`multi_worker_connection_manager.py:952`) sets `response.status_code = 206 if range_header else 200` (`:1303`) and its Content-Range/Content-Length block (`:1312-1377`) fabricates `Content-Range`/`Content-Length` **purely from the client's requested range and the previously-known full size** — neither checks what the upstream response's own status or `Content-Range` actually was. `stream_generator()` (`:1152`) is a pure passthrough of `upstream_response.iter_content()` with no offset-skipping or truncation to match the declared length. So when the upstream ignores `Range` and answers `200` with the whole asset from byte 0, the client is handed the head of the file under headers describing the requested slice — internally consistent, spec-shaped, and silently wrong. Filed as [#66](https://github.com/D10Scot/Dispatcharr/issues/66). The byte-equality assertion asked for above now exists, as `vod-range.spec.ts`'s `test.fail()` ('a provider that ignores Range still yields the requested bytes'). No second issue — #66 already covers it. Fixed in #437; the pin is now a passing `test()`. | G9 | done |
 | VOD | **Fixed by #453:** `VODCategoryFilter.m3u_account` (`apps/vod/api_views.py:624`) used to declare `NumberFilter(field_name="m3u_account__id")`, but `VODCategory` has no `m3u_account` relation — the reverse accessor is `m3u_relations` — so `GET /api/vod/categories/?m3u_account=<id>` raised `FieldError` at query time rather than filtering. `MovieFilter` and `SeriesFilter` always had this right (`m3u_relations__m3u_account__id`); only `VODCategoryFilter` did not. Was filed as [#96](https://github.com/D10Scot/Dispatcharr/issues/96). Pinned by `vod-ingest-fidelity.spec.ts` | G9 | done |
+| VOD | **Issue [#490](https://github.com/D10Scot/Dispatcharr/issues/490), no longer a hazard:** `VODCategoryViewSet.list` (`apps/vod/api_views.py`) used to `get_or_create` the movie and series `Uncategorized` categories and, for every active `enable_vod` XC account, their relations, on every `GET /api/vod/categories/`. Those relations are now created by `M3UAccountViewSet.create` and `.update` (`apps.vod.tasks.ensure_uncategorized_relations`) and by every VOD refresh, and the list is a pure read, pinned by `apps.vod.tests.test_vod_category_list_pure_read`. `vod-ingest-fidelity.spec.ts`'s `m3u_account`-filter pin asserts the account's exact five categories again | G9 | done |
 | VOD | **Fixed by #453:** `xc_get_vod_info` (`apps/output/views.py`) used to gate the whole `detailed_info` merge on `if movie.custom_properties:` and then read the data off the *relation*'s `custom_properties` instead — the wrong object's truthiness. A movie whose provider payload carries none of trailer/director/actors/backdrop has `Movie.custom_properties = None` (`clean_custom_properties({})` returns `None`), so bitrate, video, audio, the plot override and the name/year/genre/rating/id overrides never reached an XC client even though `refresh_movie_advanced_data` had just fetched and stored them on the relation (`cover_big` is unaffected — it comes from `movie_cover`, not from this merge); `/api/vod/movies/<pk>/provider-info/` reads the same relation and returns them correctly. Was filed as [#97](https://github.com/D10Scot/Dispatcharr/issues/97). Pinned by `xc-vod-catalogue.spec.ts` | G9 | done |
 | VOD | **Known defect:** `stream_xc_movie`/`stream_xc_episode` (`apps/proxy/vod_proxy/views.py`) return a bare `Response(...)` on wrong credentials, missing `xc_password`, and network-ACL denial — six call sites across both functions — but this file never imports `rest_framework.response.Response`, only `JsonResponse`/`HttpResponse`/`HttpResponseRedirect`/`Http404` from `django.http`. Every one of those branches raises `NameError: name 'Response' is not defined` instead of returning, so the client gets an unhandled 500 rather than the intended 401/403. **This is a wrong-status defect, not an authentication bypass** — the request never reaches the streaming code, so access is still refused; it just fails with the wrong status. Filed as [#100](https://github.com/D10Scot/Dispatcharr/issues/100). Pinned by `xc-vod-playback.spec.ts`'s `test.fail()` | G9 | known-bug |
 | VOD | **Fixed by #454:** `stream_xc_episode` (`apps/proxy/vod_proxy/views.py`) wrapped its `M3UEpisodeRelation` lookup in `try`/`except M3UEpisodeRelation.DoesNotExist`, but the lookup used `.filter(...).first()`, which returns `None` and never raises `DoesNotExist` — the guard was dead, and the next line dereferenced the `None` it returned, raising `AttributeError`, so an unknown episode id was a 500 rather than a 404. Now uses the `if not episode_relation` guard `stream_xc_movie` already had. Was filed as [#99](https://github.com/D10Scot/Dispatcharr/issues/99). Pinned by `xc-vod-playback.spec.ts`'s `toBe(404)` | G9 | done |
```
