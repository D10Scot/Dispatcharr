# Plan for #490 — `VODCategoryViewSet.list()` becomes a pure read

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The implementer is `sonnet`; a
> stuck implementer escalates to `opus`. The PR is reviewed by `fable` (`opus` when fable credits are
> unavailable) against this plan before it leaves draft. Steps use checkbox (`- [ ]`) syntax.

| | |
|---|---|
| goal | `GET /api/vod/categories/` (with or without `?m3u_account=`) issues no INSERT, UPDATE or DELETE. Every `enable_vod` XC account still gets its movie and series "Uncategorized" relation before its first VOD refresh, so the group filter a new account opens keeps listing them. The e2e #96 pin waits for an exact category set again. |
| issue | #490 |
| seed SHA | **`93d1e424`** (`main`, 2026-09-25). Every `file:line` below was read there with `git show "93d1e424:<path>"`. |
| PRs | **one**, small: one method deleted, one helper added, its two callers, two new test modules, two e2e specs (one predicate, comments), `e2e/README.md`, one `e2e/COVERAGE.md` row, one ledger row. |
| branch | `fix/490-vod-category-list-pure-read` (not `migration/…`: nothing under `docker/` or the relay is touched) |
| backend labels | `apps.m3u.tests`, `apps.output.tests`, `apps.vod.tests` (measured: `printf '%s\n' <the PR's paths> \| python3 scripts/ci_backend_test_labels.py` → `["apps.m3u.tests", "apps.output.tests", "apps.vod.tests"]`; `apps/vod/` routes to `apps.output.tests` too through `_PATH_ALIASES`, and `apps/m3u/api_views.py` alone → `["apps.m3u.tests"]`) |
| upstreamable | the backend half, yes: upstream `dev` (`8621e737`, 2026-09-25) carries the same `list()` override (`apps/vod/api_views.py:770`) and the same `create()`/`update()` code (`apps/m3u/api_views.py:144`, `:202`), checked with `gh api "repos/Dispatcharr/Dispatcharr/contents/<path>?ref=dev"`. The e2e, README, COVERAGE and ledger edits are fork-only. |

**What this plan finds that the issue does not say.** A reviewer should check these first.

1. **"Back to an exact count" is five, not three, and it would be five with or without this fix.** Every `enable_vod` XC account relates to both "Uncategorized" categories once any VOD refresh has run: `refresh_movies` and `refresh_series` `get_or_create` the category and the account's relation on every refresh (`apps/vod/tasks.py:187-205`, `:242-260`), and `seedCatalogue()` posts `refresh-vod/` (`e2e/tests/seeded/vod-ingest-fidelity.spec.ts:91-93`). So the `?m3u_account=` answer for that account is its three categories plus `movie/Uncategorized` and `series/Uncategorized`. The comment at `:339-344` already says "these three plus up to two Uncategorized rows, never exactly three". Measured on a private e2e stack built from the fixed tree: a `body.length === 3` predicate timed out at 120 s with `last observed: [{"id":1,"name":"Uncategorized","category_type":"movie",…`. The issue's account of the hang ("each poll added an Uncategorized row") is also slightly off: `get_or_create` adds the account's two relations on the **first** poll and nothing after, so the answer was a stable five, never three. What the pure read buys the e2e pin is that the answer no longer depends on whether *a read* has happened. The exact-five predicate passes on the seed image as well (measured, 7/7 on both images), so **the e2e change is a strengthening, not a red→green pin**. The pure-read property is pinned by the backend test (Appendix A), which is red on the seed.
2. **Deleting the override alone would regress the UI for every new account.** `M3UAccountViewSet.create()` runs `refresh_categories(account_id)` synchronously when the request has `enable_vod` (`apps/m3u/api_views.py:139-144`), and `refresh_categories` creates only the provider's categories (`apps/vod/tasks.py:129-181`, through `batch_create_categories`), never "Uncategorized". The frontend then calls `fetchCategories()` and opens the group filter at once (`frontend/src/components/forms/M3U.jsx:180-185`). That filter lists only categories with a relation to this account (`frontend/src/components/forms/VODCategoryFilter.jsx:38-51`). Today the "Uncategorized" pair appears there because that very `fetchCategories()` GET creates it. With the override gone and nothing else changed, a new account's filter would lack both until the first VOD refresh, so a user could not disable "Uncategorized" before it ingests. `refresh_account_on_save` queues nothing for an XC account (`apps/m3u/signals.py:19-20`), so that refresh does not follow creation automatically. Measured: on the seed, `test_creating_an_xc_account_with_vod_enabled_creates_both_relations` (Appendix B) fails with `AssertionError: {} != {'movie': False, 'series': False}`, which is the state this regression would leave. The fix therefore moves the block into a helper, `ensure_uncategorized_relations(account_id)`, called from `create()` (new) and from `update()` (replacing the identical inline block at `:202-238`).
3. **`update()` already creates the pair, from a stale instance.** The block at `apps/m3u/api_views.py:202-238` reads `auto_enable_new_groups_vod` from `instance`, fetched at `:150` **before** `super().update()` saves (`:192`), so a PATCH that sets `enable_vod` and `auto_enable_new_groups_vod` together used the pre-PATCH flag. The helper re-reads the account after the save, so that PATCH now uses the new flag. This is the only behaviour change to `update()`; it is the value the old `list()` would also have used had it run first.
4. **All three copies use `auto_enable_new_groups_vod` for the series relation**, while `refresh_series` reads `auto_enable_new_groups_series` (`apps/vod/tasks.py:251`). The first writer wins, since all use `get_or_create`. The helper keeps the `_vod` flag for both, exactly as `list()` and `update()` did, and its docstring says so. Changing it is out of scope (Open question Q1). The new tests set both flags to the same value, or leave both at the default, so they pin neither reading.
5. **No data migration.** An existing install where an `enable_vod` account somehow lacks the pair loses nothing but the pair's row in that account's group filter until its next VOD refresh (the account's periodic `refresh_single_m3u_account` queues `refresh_vod_content`, `apps/m3u/tasks.py:4010-4014`), which recreates it. An uncategorised movie cannot be ingested without that refresh, and `refresh_movies` creates the relation before it processes a movie. Existing rows are untouched.
6. **The two e2e specs and `e2e/README.md` document the write as a hazard, in four places.** `vod-ingest-fidelity.spec.ts:333-344` (the weakened pin), `vod-category-gating.spec.ts:301-306` ("Hazard 1" cites `VODCategoryViewSet.list`, `apps/vod/api_views.py:647`) and `:312-315` ("Hazard 2" reasons from another worker's GET), and `e2e/README.md:362-367` ("it writes rows on every call"). All four are rewritten; no assertion in `vod-category-gating.spec.ts` changes. `CLAUDE.md` names neither the endpoint nor "Uncategorized" (`git grep -n "vod/categories\|VODCategoryViewSet\|Uncategorized" 93d1e424 -- CLAUDE.md` exits 1), so it is not edited. The older G9 plan and spec (`docs/superpowers/plans/2026-08-30-e2e-vod-series.md:26`, `:876`) describe the write too; they are historical records and are not edited.
7. **Where the tests live follows routing.** The helper is defined in `apps/vod/tasks.py`, which routes to `apps.vod.tests` and `apps.output.tests` but not to `apps.m3u.tests`. Its callers are in `apps/m3u/api_views.py`, which routes only to `apps.m3u.tests`. So the helper's own tests sit in the `apps.vod.tests` module with the pure-read tests (Appendix A), and the two caller tests sit in a new `apps.m3u.tests` module (Appendix B). An edit to either file then runs the tests that pin it.

---

## Global constraints

Numbered so a step can cite one. A conflict between a constraint and a step is a STOP and report, never a judgement call.

1. **Anchor every command** with an absolute path or a leading `cd <wt> &&` (`<wt>` is your worktree). The cwd is correlated across concurrent agents (CLAUDE.md § Repository and direction). Never `cd` into another agent's worktree or into the main checkout. No bare `git stash`.
2. **`set -o pipefail`** on any pipeline whose exit status or emptiness you read. Never `2>/dev/null` a git query you interpret. Brace refs in `git show "${sha}:path"` (the zsh `:s` modifier trap).
3. **Scope is this plan's file list and nothing else.** `refresh_movies`/`refresh_series` are not refactored onto the helper, the series-flag question (finding 4) is not touched, and the historical G9 plan/spec are not edited.
4. **Byte-exact appendices.** A and B are the full text of the two new files. C–H are diff hunks against `93d1e424` that `git apply --check --whitespace=error` accepted on a fresh `git archive 93d1e424` tree. Apply them, do not retype them. I is two literal edits. If a hunk does not apply, STOP and report: the tree moved. (Open PR #506 edits `apps/vod/tasks.py` at `:495` and `:2321`; if it merges first, Appendix D still applies, at an offset, because its only hunk appends after `:2374`.)
5. **The test-modification rule.** A test changes only when the behaviour it pins is the thing being changed, and every such change is listed with its before and after (Task 5's table). Never widen a tolerance, lower a count or delete an assertion to make a run green.
6. **A break-check is not optional.** Apply the named wrong edit, run the one module, record the failure message, confirm it names the mechanism, revert.
7. **Backend runs use your own container**, never the shared `dispatcharr-testrunner`:
   `DISPATCHARR_TEST_CONTAINER=fix-490 DISPATCHARR_TEST_DB_VOLUME=fix-490-db CLAUDE_HOOK_REPO_ROOT=<wt> <wt>/.claude/hooks/start-test-container.sh`.
   Run a label with the same `docker exec` environment `.claude/hooks/pre-commit-tests.sh:158-163` uses, after `docker exec fix-490 redis-cli flushall`:
   ```bash
   docker exec fix-490 redis-cli flushall >/dev/null && docker exec \
     -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
     -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
     -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
     -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
     fix-490 /dispatcharrpy/bin/python manage.py test --keepdb <label-or-module...> -v1
   ```
   Below this is written `RUN <args>`. For a fresh-database run replace `--keepdb` with `--noinput` (without it Django prompts to delete the kept test database and dies on `EOFError`). The `PostToolUse` hook, and the commit gate, still use the shared container whatever you export: ignore their result, or note it, and never re-point the shared container. If Docker is down, say the tests did not run.
8. **Run each label once without `--keepdb`** (`--noinput`) before pushing.
9. **E2E runs use a private stack, private provider included.** At planning time the shared `e2e-upstream` answered `curl http://127.0.0.1:9402/scenarios` with an empty reply (curl exit 52) from the host while serving normally inside its container, so `scripts/e2e_up.sh` looped on "Waiting for the upstream provider" and exited 1. The procedure in Task 6 therefore starts its own provider through `DISPATCHARR_E2E_UPSTREAM_CONTAINER`/`_PORT` (`scripts/e2e_up.sh:44-52`) and tells Playwright with `E2E_UPSTREAM_CONTROL_URL`/`E2E_UPSTREAM_INTERNAL_URL` (`e2e/fixtures/upstream.ts:5-8`). **Never run `e2e_up.sh --reset`, `--down` or `--stop`**; `--recreate` is the one safe mode. Write every environment assignment out in full on each command (zsh does not word-split an unquoted `$VAR`).
10. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit with `git commit -F <file>`.
11. **The implementation PR body carries `Closes #490.`** Nothing else in this programme may: this plan's own docs PR says "Plan for #490" with no closing keyword.

---

## Overlap with sibling work

Checked at `93d1e424` with `gh pr list --repo D10Scot/Dispatcharr --state open --json number,title,headRefName,files --limit 100`: eight open PRs.

| file this PR touches | open PR or plan also touching it | resolution |
|---|---|---|
| `apps/vod/tasks.py` | #506 (`fix/468-vod-actors-non-string`), hunks at `:495` and `:2321` | independent ranges; Appendix D appends after `:2374` (constraint 4) |
| `apps/vod/api_views.py`, `apps/m3u/api_views.py` | none | — |
| `e2e/tests/seeded/vod-*.spec.ts`, `e2e/README.md`, `e2e/COVERAGE.md` | none | — |
| `metrics/curated/defects.yml` | none open as a PR; fix branches append rows | one appended row; rebase if a sibling lands first |
| this plan | #507 (`docs/plan-490-vod-category-pure-read`) is a second plan for the same issue | the orchestrator chooses one; they must not both be implemented |

---

## Decisions

1. **The fix is "move the block to a helper", not "delete the override".** Deleting alone loses the pair on a new account's group filter (finding 2). The helper lives in `apps/vod/tasks.py`, beside `refresh_movies`/`refresh_series`, which create the same rows; `apps/m3u/api_views.py` already imports from there lazily (`:142`, `:242`). It is **appended at the end of the file**, not placed near `refresh_movies`, so no existing line of `apps/vod/tasks.py` moves: the e2e specs and `e2e-upstream/` cite that file by line (`vod-category-gating.spec.ts:97`, `:212`, `:271`, `e2e-upstream/src/scenario.ts:69`, …).
2. **The helper takes an id and re-reads the account.** `ensure_uncategorized_relations(account_id)` loads `M3UAccount.objects.filter(id=account_id, account_type=XC).first()` and returns unless `custom_properties["enable_vod"]` is true. That gate is the stored value, as `list()`'s was (`apps/vod/api_views.py:671-675`), rather than `request.data`: `create()` gates on `request.data.get("enable_vod")` (`apps/m3u/api_views.py:140-141`), which for a multipart request is a string, so `"false"` is truthy there. `list()` also required `is_active=True` (`:665-668`); the helper does not, matching `update()`, which never checked it. For `create()` that is moot: `refresh_categories` raises `DoesNotExist` on an inactive account (`apps/vod/tasks.py:130`) — pre-existing, not touched.
3. **In `create()` the helper runs before `refresh_categories`.** The pair needs nothing from the provider, so it is created whether or not the provider call that follows succeeds.
4. **`update()`'s inline block becomes one helper call.** Same rows, same gate (the `old_vod_enabled`/`new_vod_enabled` condition at `:197-201` is unchanged), one behaviour change (finding 3). The comment "Create Uncategorized categories immediately so they're available in the UI" stays.
5. **`apps/vod/api_views.py` loses `list()` and the now-unused `M3UVODCategoryRelation` import.** `git grep -n "M3UVODCategoryRelation" 93d1e424 -- apps/vod/api_views.py` shows only `:18` and the deleted method; nothing imports the name from that module (`git grep -n "from apps.vod.api_views import"` exits 1).
6. **The pure-read test counts SQL verbs, not only rows.** `CaptureQueriesContext` collects every statement of the request; a write is any statement starting with `INSERT`, `UPDATE` or `DELETE`. `SAVEPOINT` statements that `get_or_create` issues are not counted, so the test fails on the write itself, not on transaction plumbing. It also asserts `VODCategory` and `M3UVODCategoryRelation` counts are unchanged, and that the answer is exactly the one seeded category. Every case starts from the state in which the old `list()` wrote four rows: an active XC account with `enable_vod`, and no "Uncategorized" row anywhere (asserted in `setUp`).
7. **The e2e pin waits for an exact typed set.** Five `category_type/name` strings, sorted, compared as a whole, so an extra row, a missing row or a movie/series swap all fail. The five-row set is right on both sides of the fix (finding 1); the comment says why.
8. **Ledger.** One appended row, `vod-category-list-writes-on-get`, `status: fixed`, `issue: 490`, `test: apps/vod/tests/test_vod_category_list_is_pure_read.py`, `fixed_in` = the implementation PR's own number, `first_seen: 2026-09-25`, `status_changed` = the date you write it. `fixed_in` needs the number, so the row goes in a second commit after the draft PR exists (`docs/agents/metrics.md:103-107`). `e2e/COVERAGE.md` gets one sentence on row `:98` (the #96 row that names the pin); no new row, since #490 has no e2e red→green pin.

---

## PR: `fix/490-vod-category-list-pure-read`

- **Closes** #490 (in the implementation PR body only; constraint 11).
- **Files**
  - `apps/vod/api_views.py` (Appendix C)
  - `apps/vod/tasks.py` (Appendix D)
  - `apps/m3u/api_views.py` (Appendix E)
  - `apps/vod/tests/test_vod_category_list_is_pure_read.py` (new, Appendix A)
  - `apps/m3u/tests/test_enable_vod_creates_uncategorized.py` (new, Appendix B)
  - `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` (Appendix F)
  - `e2e/tests/seeded/vod-category-gating.spec.ts` (Appendix G, comments only)
  - `e2e/README.md` (Appendix H)
  - `e2e/COVERAGE.md`, `metrics/curated/defects.yml` (Appendix I)
- **Labels** `apps.m3u.tests`, `apps.output.tests`, `apps.vod.tests`.

### Tasks

- [ ] **Task 0 — worktree, container, baseline.** Create your own worktree and branch off `origin/main`: `git -C /Users/dion/git/Dispatcharr worktree add /Users/dion/git/Dispatcharr/.worktrees/fix-490 -b fix/490-vod-category-list-pure-read origin/main`. Confirm `git -C <wt> rev-parse --short HEAD` is `93d1e424` or a descendant. If a descendant, extract each fenced `diff` block of Appendices C–H to a scratch file and run `git -C <wt> apply --check --whitespace=error <file>` on each; STOP if any fails. Start the container (constraint 7) and take the baseline, one label per run, fresh database:
  ```bash
  RUN --noinput apps.vod.tests      # then apps.output.tests, then apps.m3u.tests
  ```
  Expected at `93d1e424` (measured): `apps.vod.tests` `Ran 85 tests` `OK`; `apps.output.tests` `Ran 121 tests` `OK`; `apps.m3u.tests` `Ran 245 tests` `OK`. Record yours; if HEAD is a descendant the counts may be higher.

- [ ] **Task 1 — the tests, red.** Create `apps/vod/tests/test_vod_category_list_is_pure_read.py` from **Appendix A** and `apps/m3u/tests/test_enable_vod_creates_uncategorized.py` from **Appendix B**, verbatim. Run both modules on the unfixed tree:
  ```bash
  RUN apps.vod.tests.test_vod_category_list_is_pure_read apps.m3u.tests.test_enable_vod_creates_uncategorized
  ```
  Expected (measured at `93d1e424`): `Ran 8 tests`, `FAILED (failures=3, errors=3)`, exactly:
  - `FAIL: test_listing_categories_writes_nothing` and `FAIL: test_listing_one_accounts_categories_writes_nothing`, each `AssertionError: Lists differ: ['INSERT INTO "vod_vodcategory" ("name", "[… chars]id"'] != []` followed by `First list contains 4 additional elements.` and `First extra element 0: 'INSERT INTO "vod_vodcategory" ("name", "category_type", "created_at", "updated_at") VALUES ('Uncategorized', 'movie', …`. The `[… chars]` count varies with the timestamps (1112–1116 measured). Four inserts: two categories, two relations. This is the defect.
  - `FAIL: test_creating_an_xc_account_with_vod_enabled_creates_both_relations`, `AssertionError: {} != {'movie': False, 'series': False}` — finding 2's gap: on the seed only the listing creates the pair for a new account.
  - `ERROR:` on the three `EnsureUncategorizedRelationsTests` cases, each `ImportError: cannot import name 'ensure_uncategorized_relations' from 'apps.vod.tasks'` — the helper does not exist yet. The import is per test, so the listing tests above still reach their own assertion.
  - `test_creating_an_xc_account_without_vod_creates_neither` and `test_enabling_vod_on_an_existing_account_creates_both_relations` **pass** on the seed. The second is the control that the `update()` refactor keeps what `update()` already did.

- [ ] **Task 2 — the fix, green.** Apply **Appendices C, D and E** (`git -C <wt> apply --whitespace=error <scratch>/C.diff`, and so on). Re-run the Task 1 command. Expected (measured): `Ran 8 tests`, `OK`. Then `cd <wt> && python3 scripts/check_credential_logging.py apps/vod/api_views.py apps/vod/tasks.py apps/m3u/api_views.py apps/vod/tests/test_vod_category_list_is_pure_read.py apps/m3u/tests/test_enable_vod_creates_uncategorized.py; echo "exit=$?"`, expecting `exit=0` (measured).

- [ ] **Task 3 — break-checks.** First copy the three fixed files aside: `cp <wt>/apps/vod/api_views.py <scratch>/vod_api_views.py; cp <wt>/apps/vod/tasks.py <scratch>/vod_tasks.py; cp <wt>/apps/m3u/api_views.py <scratch>/m3u_api_views.py`. Each check is one wrong edit, one module, then a revert by copying the saved file back. Every message below was measured.
  1. **A `list()` that calls the helper** (the plausible wrong fix: "moved to a helper" but still called from the read). In `apps/vod/api_views.py`, inside `VODCategoryViewSet`, after `get_permissions`, add:
     ```python
         def list(self, request, *args, **kwargs):
             from apps.m3u.models import M3UAccount
             from .tasks import ensure_uncategorized_relations

             for account_id in M3UAccount.objects.filter(is_active=True).values_list("id", flat=True):
                 ensure_uncategorized_relations(account_id)
             return super().list(request, *args, **kwargs)
     ```
     `RUN apps.vod.tests.test_vod_category_list_is_pure_read` → `FAILED (failures=2)`: both listing tests, `First list contains 4 additional elements.`, first extra element `INSERT INTO "vod_vodcategory" … ('Uncategorized', 'movie', …`. Names the mechanism: the read inserts the Uncategorized rows. Revert.
  2. **`create()` without the helper.** In `apps/m3u/api_views.py` delete the line `                ensure_uncategorized_relations(account_id)`. `RUN apps.m3u.tests.test_enable_vod_creates_uncategorized` → `FAILED (failures=1)`: `test_creating_an_xc_account_with_vod_enabled_creates_both_relations`, `AssertionError: {} != {'movie': False, 'series': False}`. Revert.
  3. **`update()` without the helper.** Delete `            ensure_uncategorized_relations(instance.id)`. Same module → `FAILED (failures=1)`: `test_enabling_vod_on_an_existing_account_creates_both_relations`, `AssertionError: {} != {'movie': True, 'series': True}`. Revert.
  4. **The helper ignores `enable_vod`.** In `apps/vod/tasks.py` delete the two lines `    if not custom_props.get("enable_vod", False):` / `        return`. `RUN apps.vod.tests.test_vod_category_list_is_pure_read` → `FAILED (failures=1)`: `test_an_xc_account_without_vod_gets_nothing`, `AssertionError: {'movie': True, 'series': True} != {}`. Revert.
  5. **The helper ignores the account type.** Replace `id=account_id, account_type=M3UAccount.Types.XC` with `id=account_id`. Same module → `FAILED (failures=1)`: `test_a_standard_account_gets_nothing`, `AssertionError: {'movie': True, 'series': True} != {}`. Revert.

  After the reverts, re-run the Task 1 command (`Ran 8 tests`, `OK`), and confirm `git -C <wt> diff 93d1e424 -- apps/vod/api_views.py apps/vod/tasks.py apps/m3u/api_views.py` is exactly Appendices C, D and E.

- [ ] **Task 4 — the labels.** Fresh database, one label per run: `RUN --noinput apps.vod.tests`, `apps.output.tests`, `apps.m3u.tests`. Expected (measured): `apps.vod.tests` `Ran 90 tests` `OK` (85 + 5); `apps.output.tests` `Ran 121 tests` `OK` (unchanged); `apps.m3u.tests` `Ran 248 tests` `OK` (245 + 3). Also `cd <wt> && git status --porcelain --untracked-files=all | cut -c4- | python3 scripts/ci_backend_test_labels.py` (the two new test modules are untracked until Task 7, so `git diff` alone would miss them), expecting `["apps.m3u.tests", "apps.output.tests", "apps.vod.tests"]`.

- [ ] **Task 5 — the e2e edits.** Apply **Appendices F, G and H**, and make the `e2e/COVERAGE.md` edit of **Appendix I.1**. Then `cd <wt>/e2e && npm ci && npx tsc --noEmit -p .; echo "exit=$?"` (expect `exit=0`, measured) and `npx playwright test --project=guards --reporter=line 2>&1 | tail -1` (expect `50 passed`, measured). The `PostToolUse` hook also runs `tsc` on each edited `.ts` file.

  | Test | Before | After |
  |---|---|---|
  | `vod-ingest-fidelity.spec.ts` `'GET /api/vod/categories/ accepts an m3u_account filter'` (`:282`), the wait at `:345-350` | `waitFor.resource(url, (body) => expectedNames.every((n) => body.some((c) => c.name === n)), …)` over the three `${prefix}` names, then a loop `expect(category, …).toBeDefined()` per name | `waitFor.resource(url, (body) => JSON.stringify(typedNames(body)) === JSON.stringify(expected), …)` where `expected` is the sorted five `category_type/name` strings (three `${prefix}` categories, `movie/Uncategorized`, `series/Uncategorized`), then `expect(typedNames(categories), …).toEqual(expected)`. The per-name loop is subsumed by the exact equality and removed. The comment at `:333-344` is rewritten. The status one-shot above and the two scoping assertions below are unchanged. |
  | `vod-category-gating.spec.ts` `'an uncategorised movie or series falls back …'` (`:239`) | "Hazard 1" (`:301-306`) and "Hazard 2" (`:312-315`) comments reason from the GET's writes | Comments rewritten to reason from creation and refresh. **No assertion changes.** |

- [ ] **Task 6 — the e2e run, on a private stack (constraint 9).** `<scratch>` is your scratchpad; `<base>` is the SHA your branch forked from. The "before" image is built from `<base>`, the "after" image from `<wt>`. The spec files are always run from `<wt>`.
  1. `git -C <wt> worktree add --detach <scratch>/base-490 <base>`
  2. Before image and stack (drop `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1` only if `docker image inspect dispatcharr-e2e-upstream:local` fails):
     ```bash
     DISPATCHARR_E2E_CONTAINER=e2e-fix-490 DISPATCHARR_E2E_VOLUME=e2e-fix-490-data \
     DISPATCHARR_E2E_PORT=9197 DISPATCHARR_E2E_NETWORK=e2e-fix-490-net \
     DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 \
     DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-fix-490 DISPATCHARR_E2E_UPSTREAM_PORT=9412 \
     DISPATCHARR_E2E_IMAGE=dispatcharr-e2e:fix-490-before \
       <scratch>/base-490/scripts/e2e_up.sh
     ```
     Pick other ports if `9197` or `9412` is taken (`docker ps --format '{{.Names}} {{.Ports}}'`).
  3. Run both specs:
     ```bash
     cd <wt>/e2e && E2E_BASE_URL=http://localhost:9197 E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9412 \
       E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-fix-490:8080 DISPATCHARR_E2E_CONTAINER=e2e-fix-490 \
       npx playwright test --project=seeded tests/seeded/vod-ingest-fidelity.spec.ts \
       tests/seeded/vod-category-gating.spec.ts --reporter=json > <scratch>/e2e-before.json
     ```
     Expected (measured): exit 0, `expected: 7, unexpected: 0` (bootstrap plus six seeded tests). It passes on the unfixed image **by design** (finding 1).
  4. After image into the same container name and volume, built from `<wt>`:
     ```bash
     DISPATCHARR_E2E_CONTAINER=e2e-fix-490 DISPATCHARR_E2E_VOLUME=e2e-fix-490-data \
     DISPATCHARR_E2E_PORT=9197 DISPATCHARR_E2E_NETWORK=e2e-fix-490-net \
     DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 \
     DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-fix-490 DISPATCHARR_E2E_UPSTREAM_PORT=9412 \
     DISPATCHARR_E2E_IMAGE=dispatcharr-e2e:fix-490-after \
       <wt>/scripts/e2e_up.sh --recreate
     ```
     Confirm `docker inspect e2e-fix-490 --format '{{.Config.Image}}'` prints `dispatcharr-e2e:fix-490-after`, then re-run step 3 into `<scratch>/e2e-after.json`. Expected (measured): exit 0, `expected: 7, unexpected: 0`.
  5. **Break-check (the exact count is five, not three).** Temporarily replace `    (body) => JSON.stringify(typedNames(body)) === JSON.stringify(expected),` with `    (body) => body.length === 3,` and run only the filter test against the after image (step 3's command with `-g "accepts an m3u_account filter"`). Expected (measured): it fails after 120 s with `timed out after 120000ms waiting for exactly the 3 … categories and both Uncategorized via the m3u_account filter (last observed: [{"id":…,"name":"Uncategorized","category_type":"movie",…`. Revert, and confirm with `git -C <wt> diff 93d1e424 -- e2e/tests/seeded/vod-ingest-fidelity.spec.ts` that the file matches Appendix F again.
  6. Tear down only your own objects: `docker rm -f e2e-fix-490 e2e-upstream-fix-490`, `docker volume rm e2e-fix-490-data`, `docker network rm e2e-fix-490-net`, `docker rmi dispatcharr-e2e:fix-490-before dispatcharr-e2e:fix-490-after`, `git -C <wt> worktree remove <scratch>/base-490`. Do not touch `e2e-upstream` or any network you did not create.

  Reading the JSON: each test is at `suites[].specs[]`, recursing through nested `suites[]`, with `tests[].results[].status`; `stats` has `expected`/`unexpected`.

- [ ] **Task 7 — commit, push, open the draft PR.** One commit with the code, tests and e2e/docs edits (not yet the ledger), subject `fix(vod): GET /api/vod/categories/ is a pure read; enabling VOD creates the Uncategorized pair (#490)`. Stage and commit in separate calls (constraint 10); the gate runs `apps.m3u.tests`, `apps.output.tests` and `apps.vod.tests` in the shared container, so note its result or its "did NOT run" warning rather than relying on it. Push and open a **draft** PR against `main` with the body below.

- [ ] **Task 8 — the ledger, second commit.** With the PR number `<N>` from Task 7, append the row in **Appendix I.2** to `metrics/curated/defects.yml`, substituting `<N>` and today's date. Then `cd <wt> && python3 -m metrics.build --validate-only; echo "exit=$?"`. Expected (measured with a placeholder number): `ok: 46 metrics, 37 milestones, 47 defects`, `exit=0`. Also `bash <wt>/scripts/run_metrics_tests.sh build 2>&1 | tail -1` → `OK` (measured: `Ran 102 tests`). Commit (`chore(metrics): ledger row for #490`), push.

**Tests added:** `apps/vod/tests/test_vod_category_list_is_pure_read.py` (5 cases), `apps/m3u/tests/test_enable_vod_creates_uncategorized.py` (3 cases). **Tests changed:** the two e2e specs, per Task 5's table. **Tests removed:** none.

### PR description draft (implementation PR)

> **fix(vod): GET /api/vod/categories/ is a pure read; enabling VOD creates the Uncategorized pair (#490)**
>
> `VODCategoryViewSet.list()` used to `get_or_create` a movie and a series "Uncategorized" category, and a relation to each, for every active XC account with `enable_vod` — on every GET. The override is deleted; the listing now only reads.
>
> The rows are still created where they were needed. VOD refreshes already create them (`refresh_movies`/`refresh_series`, unchanged). The one place that relied on the read was a new account's group filter: `M3UAccountViewSet.create()` builds only the provider's categories, and the frontend's `fetchCategories()` straight after creation was what added the pair. `create()` now calls a new helper, `apps.vod.tasks.ensure_uncategorized_relations`, and `update()`'s identical inline block for the `enable_vod` off→on flip is replaced by the same call. The helper re-reads the account after the save, so a PATCH that sets `enable_vod` and `auto_enable_new_groups_vod` together now uses the new flag.
>
> `vod-ingest-fidelity.spec.ts`'s #96 pin waits for the account's exact category set again. That set is five rows (its three categories plus both "Uncategorized"), not three: every VOD refresh relates the account to the pair, so an exact-three wait never settles on either side of this fix.
>
> Closes #490.
>
> Evidence:
> - Red on the unfixed tree: <paste Task 1>.
> - Green: <paste Task 2>. Break-checks: <paste Task 3's five>.
> - Labels (fresh DB): <paste Task 4>.
> - e2e, private stack, before and after images: <paste Task 6's two stats lines>; exact-three break-check: <paste>.
> - `tsc`, guards, metrics validator: <paste>.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Open questions (for the user; none blocks the implementation)

- **Q1.** The series "Uncategorized" relation takes `auto_enable_new_groups_vod` when created at account creation or VOD enable (as it always has), but `auto_enable_new_groups_series` when a refresh creates it first (finding 4). Should the helper read `_series` for the series relation? Doing so is a one-line change, but it changes what a user who set the two flags differently sees on a new account, so it is left out here. Default: leave it, and file a follow-up if wanted.

## Not verified by the planner

- The commit gate and the `PostToolUse` hook were not exercised: the prototype was edited with shell writes, not the Edit tool, so the shared `dispatcharr-testrunner` never ran. Every backend figure above comes from the private container `fixplan-490-b2` (image `ghcr.io/d10scot/dispatcharr:latest`, repo bind-mounted read-only).
- `python3 -m metrics.build --validate-only` was run in the planner's worktree with a placeholder `fixed_in: 999`; `docs/agents/metrics.md:27-28` says an unmerged `fixed_in` is accepted offline, and only `--check-prs` would reject it.
- The frontend was not run: the UI regression in finding 2 is inferred from `M3U.jsx:180-185`, `VODCategoryFilter.jsx:38-51` and the red create test, not observed in a browser.
- The full seeded e2e project was not run, only the two edited specs (7 tests with bootstrap). The two other specs that read `/api/vod/categories/` (`vod-fixture.spec.ts:88-101`, `xc-vod-catalogue.spec.ts:102-113`; `git grep -n "vod/categories" 93d1e424 -- e2e/tests` lists four files) locate their own generated category by name and never touch an "Uncategorized" row, so they do not depend on the removed write, but they were not run.

---

## Appendix A — `apps/vod/tests/test_vod_category_list_is_pure_read.py` (new file, verbatim)

````python
"""GET /api/vod/categories/ is a pure read (#490).

VODCategoryViewSet.list() used to get_or_create a movie and a series
"Uncategorized" VODCategory, and an M3UVODCategoryRelation to each, for every
active XC account with enable_vod, on every call. A read created rows, so an
e2e wait for an account's exact category set
(e2e/tests/seeded/vod-ingest-fidelity.spec.ts) had to settle for a membership
predicate (#453). The listing now only reads. The rows are created where VOD
is enabled on an account, through ensure_uncategorized_relations
(apps.m3u.tests.test_enable_vod_creates_uncategorized pins both callers), and
on every VOD refresh (refresh_movies / refresh_series, unchanged).

The helper's own tests live here rather than beside its callers because it is
defined in apps/vod/tasks.py, which routes to this label and not to
apps.m3u.tests.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UVODCategoryRelation, VODCategory

User = get_user_model()

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE")


def _account(name, account_type=M3UAccount.Types.XC, **custom_properties):
    return M3UAccount.objects.create(
        name=name,
        server_url=f"http://{name}.example",
        account_type=account_type,
        is_active=True,
        custom_properties=custom_properties,
    )


def _uncategorized(account):
    return {
        rel.category.category_type: rel.enabled
        for rel in M3UVODCategoryRelation.objects.filter(
            m3u_account=account, category__name="Uncategorized"
        ).select_related("category")
    }


class VodCategoryListIsPureReadTests(TestCase):
    """Each test starts in the state where the old list() inserted four rows:
    an active XC account with enable_vod, and no "Uncategorized" row anywhere."""

    def setUp(self):
        admin = User.objects.create_user(username="vodcatpure", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.account = _account("vod-on", enable_vod=True, auto_enable_new_groups_vod=True)
        category = VODCategory.objects.create(name="pure-read-movies", category_type="movie")
        M3UVODCategoryRelation.objects.create(m3u_account=self.account, category=category)
        self.assertFalse(VODCategory.objects.filter(name="Uncategorized").exists())

    def _counts(self):
        return VODCategory.objects.count(), M3UVODCategoryRelation.objects.count()

    def _list(self, params):
        before = self._counts()
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get("/api/vod/categories/", params)
        self.assertEqual(res.status_code, 200)
        writes = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith(WRITE_VERBS)
        ]
        body = res.json()
        rows = body["results"] if isinstance(body, dict) else body
        return before, writes, [r["name"] for r in rows]

    def test_listing_categories_writes_nothing(self):
        before, writes, names = self._list({})
        self.assertEqual(writes, [])
        self.assertEqual(self._counts(), before)
        self.assertEqual(names, ["pure-read-movies"])

    def test_listing_one_accounts_categories_writes_nothing(self):
        before, writes, names = self._list({"m3u_account": self.account.id})
        self.assertEqual(writes, [])
        self.assertEqual(self._counts(), before)
        self.assertEqual(names, ["pure-read-movies"])


class EnsureUncategorizedRelationsTests(TestCase):
    # Imported per test, not at module level, so the listing tests above run
    # (and fail on their own assertion) on a tree that predates the helper.

    def test_an_xc_account_with_vod_gets_both_relations_once(self):
        from apps.vod.tasks import ensure_uncategorized_relations

        account = _account("helper-on", enable_vod=True, auto_enable_new_groups_vod=False)
        ensure_uncategorized_relations(account.id)
        ensure_uncategorized_relations(account.id)
        self.assertEqual(set(_uncategorized(account)), {"movie", "series"})
        self.assertFalse(_uncategorized(account)["movie"])
        self.assertEqual(M3UVODCategoryRelation.objects.filter(m3u_account=account).count(), 2)
        self.assertEqual(VODCategory.objects.filter(name="Uncategorized").count(), 2)

    def test_an_xc_account_without_vod_gets_nothing(self):
        from apps.vod.tasks import ensure_uncategorized_relations

        account = _account("helper-off", enable_vod=False)
        ensure_uncategorized_relations(account.id)
        self.assertEqual(_uncategorized(account), {})
        self.assertFalse(VODCategory.objects.filter(name="Uncategorized").exists())

    def test_a_standard_account_gets_nothing(self):
        from apps.vod.tasks import ensure_uncategorized_relations

        account = _account("helper-std", account_type=M3UAccount.Types.STADNARD, enable_vod=True)
        ensure_uncategorized_relations(account.id)
        self.assertEqual(_uncategorized(account), {})
        self.assertFalse(VODCategory.objects.filter(name="Uncategorized").exists())
````

## Appendix B — `apps/m3u/tests/test_enable_vod_creates_uncategorized.py` (new file, verbatim)

````python
"""Enabling VOD on an XC account creates its two "Uncategorized" relations (#490).

GET /api/vod/categories/ used to create them on every call, for every active
XC account with enable_vod, and the group filter a new account opens straight
after creation (frontend/src/components/forms/M3U.jsx's handleNewPlaylist)
relied on that call to list them. The listing is now a pure read
(apps.vod.tests.test_vod_category_list_is_pure_read), so both places VOD
becomes enabled -- M3UAccountViewSet.create() and update() -- create them
through apps.vod.tasks.ensure_uncategorized_relations. The provider calls
each path makes are patched out: these tests are about the rows, not the
refresh.
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UVODCategoryRelation

User = get_user_model()


class EnableVodCreatesUncategorizedTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="vodenableadmin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)

    def _uncategorized(self, account_id):
        return {
            rel.category.category_type: rel.enabled
            for rel in M3UVODCategoryRelation.objects.filter(
                m3u_account_id=account_id, category__name="Uncategorized"
            ).select_related("category")
        }

    def _create(self, **fields):
        body = {
            "name": "xc-vod",
            "account_type": "XC",
            "server_url": "http://xc.example",
            "username": "u",
            "password": "p",
            "is_active": True,
            **fields,
        }
        with mock.patch("apps.m3u.api_views.refresh_m3u_groups"), mock.patch(
            "apps.vod.tasks.refresh_categories"
        ) as refresh_categories:
            res = self.client.post("/api/m3u/accounts/", body, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()["id"], refresh_categories

    def test_creating_an_xc_account_with_vod_enabled_creates_both_relations(self):
        account_id, refresh_categories = self._create(
            enable_vod=True,
            auto_enable_new_groups_vod=False,
            auto_enable_new_groups_series=False,
        )
        refresh_categories.assert_called_once_with(account_id)
        self.assertEqual(self._uncategorized(account_id), {"movie": False, "series": False})

    def test_creating_an_xc_account_without_vod_creates_neither(self):
        account_id, refresh_categories = self._create(enable_vod=False)
        refresh_categories.assert_not_called()
        self.assertEqual(self._uncategorized(account_id), {})

    def test_enabling_vod_on_an_existing_account_creates_both_relations(self):
        account = M3UAccount.objects.create(
            name="xc-later",
            server_url="http://xc-later.example",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": False},
        )
        with mock.patch("apps.vod.tasks.refresh_vod_content") as refresh_vod_content:
            res = self.client.patch(
                f"/api/m3u/accounts/{account.id}/", {"enable_vod": True}, format="json"
            )
        self.assertEqual(res.status_code, 200, res.content)
        refresh_vod_content.delay.assert_called_once_with(account.id)
        self.assertEqual(self._uncategorized(account.id), {"movie": True, "series": True})
````

## Appendix C — `apps/vod/api_views.py` (against `93d1e424`)

The unused import (`:18`) and `VODCategoryViewSet.list()` (`:647-698`).

````diff
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
````

## Appendix D — `apps/vod/tasks.py` (against `93d1e424`)

The helper, appended after the last line (`:2374`) so no existing line moves (Decision 1).

````diff
diff --git a/apps/vod/tasks.py b/apps/vod/tasks.py
index 07d92c75..c57645a8 100644
--- a/apps/vod/tasks.py
+++ b/apps/vod/tasks.py
@@ -2372,3 +2372,44 @@ def refresh_movie_advanced_data(m3u_movie_relation_id, force_refresh=False):
     except Exception as e:
         logger.error(f"Error refreshing advanced movie data for relation {m3u_movie_relation_id}: {str(e)}")
         return f"Error: {str(e)}"
+
+
+def ensure_uncategorized_relations(account_id):
+    """Create the movie and series "Uncategorized" categories, and this
+    account's relation to each, when it is an XC account with VOD enabled.
+
+    Called where VOD becomes enabled on an account -- M3UAccountViewSet's
+    create() and update() -- so both categories appear in the account's group
+    filter before its first VOD refresh; refresh_movies and refresh_series
+    get_or_create the same rows on every refresh. Until #490 the listing,
+    GET /api/vod/categories/, did this for every such account on every call.
+    It is now a pure read, so this is the only place outside a refresh that
+    creates them.
+
+    Both relations take auto_enable_new_groups_vod, as the listing did;
+    refresh_series reads auto_enable_new_groups_series, but get_or_create
+    means whichever runs first decides.
+    """
+    account = M3UAccount.objects.filter(
+        id=account_id, account_type=M3UAccount.Types.XC
+    ).first()
+    if account is None:
+        return
+    custom_props = account.custom_properties or {}
+    if not custom_props.get("enable_vod", False):
+        return
+    auto_enable_new = custom_props.get("auto_enable_new_groups_vod", True)
+    for category_type in ("movie", "series"):
+        category, _ = VODCategory.objects.get_or_create(
+            name="Uncategorized",
+            category_type=category_type,
+            defaults={}
+        )
+        M3UVODCategoryRelation.objects.get_or_create(
+            category=category,
+            m3u_account=account,
+            defaults={
+                'enabled': auto_enable_new,
+                'custom_properties': {}
+            }
+        )
````

## Appendix E — `apps/m3u/api_views.py` (against `93d1e424`)

`create()` (`:139-144`) and `update()` (`:202-238`).

````diff
diff --git a/apps/m3u/api_views.py b/apps/m3u/api_views.py
index 26eaf342..e6f8e6f6 100644
--- a/apps/m3u/api_views.py
+++ b/apps/m3u/api_views.py
@@ -139,8 +139,12 @@ class M3UAccountViewSet(viewsets.ModelViewSet):
             # Check if VOD is enabled
             enable_vod = request.data.get("enable_vod", False)
             if enable_vod:
-                from apps.vod.tasks import refresh_categories
+                from apps.vod.tasks import (
+                    ensure_uncategorized_relations,
+                    refresh_categories,
+                )
 
+                ensure_uncategorized_relations(account_id)
                 refresh_categories(account_id)
 
         # After the instance is created, return the response
@@ -200,43 +204,9 @@ class M3UAccountViewSet(viewsets.ModelViewSet):
             and new_vod_enabled
         ):
             # Create Uncategorized categories immediately so they're available in the UI
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
+            from apps.vod.tasks import ensure_uncategorized_relations
 
-            M3UVODCategoryRelation.objects.get_or_create(
-                category=series_category,
-                m3u_account=instance,
-                defaults={
-                    'enabled': auto_enable_new,
-                    'custom_properties': {}
-                }
-            )
+            ensure_uncategorized_relations(instance.id)
 
             # Trigger full VOD refresh
             from apps.vod.tasks import refresh_vod_content
````

## Appendix F — `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` (against `93d1e424`)

````diff
diff --git a/e2e/tests/seeded/vod-ingest-fidelity.spec.ts b/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
index 03145c99..4be42814 100644
--- a/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
+++ b/e2e/tests/seeded/vod-ingest-fidelity.spec.ts
@@ -333,26 +333,34 @@ test('GET /api/vod/categories/ accepts an m3u_account filter', { tag: '@contract
   // Still not deterministic on status alone: refresh_vod_content is a
   // separate Celery task queued by the 202 above, not completed by it, so a
   // read straight after the POST can return 200 with zero rows whether the
-  // filter is scoping correctly or not. Wait for the three ${prefix}
-  // categories the category-rows test above declares, the same way it does,
-  // but through the m3u_account filter instead of name — that is the
-  // property under test. Not an exact-length predicate: VODCategoryViewSet.list()
-  // (apps/vod/api_views.py) also get_or_creates a movie and a series
-  // "Uncategorized" category and relation for every active XC account with
-  // VOD enabled, including this one, on every call to this same endpoint —
-  // so a correctly-scoped answer for this account is these three plus up to
-  // two Uncategorized rows, never exactly three.
-  const expectedNames = [`${prefix}-movies-a`, `${prefix}-movies-b`, `${prefix}-shows`];
+  // filter is scoping correctly or not. Wait for this account's exact
+  // category set through the m3u_account filter — that is the property under
+  // test. It is five rows, not three: the three ${prefix} categories the
+  // category-rows test above declares, plus the movie and the series
+  // "Uncategorized" category, which every enable_vod XC account relates to.
+  // Creating the account created those two relations
+  // (ensure_uncategorized_relations, called from M3UAccountViewSet.create)
+  // and every VOD refresh get_or_creates them again (refresh_movies /
+  // refresh_series). This read creates nothing: since #490
+  // GET /api/vod/categories/ is a pure read, so every poll sees the same
+  // answer and an exact set is safe to wait for. Until then the read itself
+  // get_or_created both relations for every enable_vod XC account, and this
+  // wait was a membership predicate.
+  const expected = [
+    `movie/${prefix}-movies-a`,
+    `movie/${prefix}-movies-b`,
+    `series/${prefix}-shows`,
+    'movie/Uncategorized',
+    'series/Uncategorized',
+  ].sort();
+  const typedNames = (body: VodCategory[]) => body.map((c) => `${c.category_type}/${c.name}`).sort();
   const categories = await waitFor.resource<VodCategory[]>(
     url,
-    (body) => expectedNames.every((n) => body.some((c) => c.name === n)),
-    { description: `all 3 ${prefix} categories via the m3u_account filter`, timeoutMs: 120_000 }
+    (body) => JSON.stringify(typedNames(body)) === JSON.stringify(expected),
+    { description: `exactly the 3 ${prefix} categories and both Uncategorized via the m3u_account filter`, timeoutMs: 120_000 }
   );
+  expect(typedNames(categories), `account ${account.id}'s m3u_account-filtered categories`).toEqual(expected);
 
-  for (const name of expectedNames) {
-    const category = categories.find((c) => c.name === name);
-    expect(category, `${name} among the m3u_account-filtered categories`).toBeDefined();
-  }
   // Every returned row must actually relate to this account, and the decoy
   // account's category must be absent — together these are guaranteed (not
   // merely likely) to fail an unfiltered list or a wrongly `gte`-scoped one,
````

## Appendix G — `e2e/tests/seeded/vod-category-gating.spec.ts` (against `93d1e424`)

Comments only.

````diff
diff --git a/e2e/tests/seeded/vod-category-gating.spec.ts b/e2e/tests/seeded/vod-category-gating.spec.ts
index afe6bf9c..74d9c9b7 100644
--- a/e2e/tests/seeded/vod-category-gating.spec.ts
+++ b/e2e/tests/seeded/vod-category-gating.spec.ts
@@ -298,21 +298,25 @@ test('an uncategorised movie or series falls back to the Uncategorized category,
 
   const categories = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
 
-  // Hazard 1: `GET /api/vod/categories/` itself get_or_creates these two
-  // Uncategorized relations for every enable_vod XC account
-  // (`VODCategoryViewSet.list`, apps/vod/api_views.py:647), with
-  // `defaults={'enabled': auto_enable_new}` — so this assertion holds
-  // whether the refresh above created the relation or this very GET did.
-  // Nothing here claims the refresh was what created it.
+  // Hazard 1: the refresh above is not the only thing that creates these
+  // two Uncategorized relations. Creating the account with enable_vod
+  // already did (`ensure_uncategorized_relations`, called from
+  // `M3UAccountViewSet.create`), with `defaults={'enabled':
+  // auto_enable_new_groups_vod}` for both — false here, like the series flag
+  // refresh_series reads — so this assertion holds whichever of the two
+  // created the relation. Nothing here claims the refresh was what created
+  // it. (`GET /api/vod/categories/` created them too until #490; it is a
+  // pure read now.)
   const uncategorizedMovieCat = categories.find(
     (c) => c.name === 'Uncategorized' && c.category_type === 'movie'
   )!;
   expect(uncategorizedMovieCat).toBeTruthy();
   const movieRelation = uncategorizedMovieCat.m3u_accounts.find((r) => r.m3u_account === account.id)!;
-  // Hazard 2: never assert the ABSENCE of this relation for any account —
-  // any other worker's own `GET /api/vod/categories/` call would create one
-  // for its own account, but never for this one (the relation is scoped by
-  // m3u_account), so only presence is safe to assert here.
+  // Hazard 2: never assert the ABSENCE of an Uncategorized relation for an
+  // enable_vod account — every one, other workers' included, gets its own at
+  // creation and on every VOD refresh. The relation is scoped by
+  // m3u_account, so presence for THIS account is what is safe to assert
+  // here.
   expect(movieRelation).toBeTruthy();
   expect(movieRelation.enabled).toBe(false);
 
````

## Appendix H — `e2e/README.md` (against `93d1e424`)

````diff
diff --git a/e2e/README.md b/e2e/README.md
index c4580f5c..b6f12d6b 100644
--- a/e2e/README.md
+++ b/e2e/README.md
@@ -359,12 +359,15 @@ applies to channels elsewhere in this harness. Scope every assertion by both `?m
 generated name; a fixed literal name will collide with another worker's or another test's catalogue
 on a shared instance.
 
-**`GET /api/vod/categories/` is unpaginated, and it writes rows on every call.** Its `list()`
-`get_or_create`s the two `Uncategorized` categories (movie and series) and their
-`M3UVODCategoryRelation` rows for *every* active `enable_vod` XC account on the instance — including
-other workers'. Locate your category with `find`, never a length or an index, and never assert that
-an account *lacks* an `Uncategorized` relation — another test's `GET` may have created it moments
-before yours ran.
+**`GET /api/vod/categories/` is unpaginated, and every `enable_vod` XC account relates to both
+`Uncategorized` categories.** The listing is a pure read since #490, but creating an XC account with
+`enable_vod` (or turning it on later) creates the movie and series `Uncategorized` categories and
+that account's relation to each (`ensure_uncategorized_relations`), and every VOD refresh
+`get_or_create`s them again — for other workers' accounts too. So an account's `?m3u_account=`
+answer is its own categories plus those two, and the unfiltered list carries both `Uncategorized`
+rows. Locate your category with `find`, or wait for an exact set scoped by `?m3u_account=`; never
+use a length or an index on the unfiltered list, and never assert that an `enable_vod` account
+*lacks* an `Uncategorized` relation.
 
 **The four Lua scripts in `vod_proxy`'s stream counter are off limits.** They bypass the session
 metadata lock deliberately, as a real bug fix pinned by
````

## Appendix I — the COVERAGE sentence and the ledger row

**I.1 `e2e/COVERAGE.md:98`.** The literal below occurs exactly once at `93d1e424`; replace it with the Edit tool.

- old: ``Was filed as [#96](https://github.com/D10Scot/Dispatcharr/issues/96). Pinned by `vod-ingest-fidelity.spec.ts` | G9 | done |``
- new: ``Was filed as [#96](https://github.com/D10Scot/Dispatcharr/issues/96). Pinned by `vod-ingest-fidelity.spec.ts`, which since [#490](https://github.com/D10Scot/Dispatcharr/issues/490) waits for the account's exact five-row set (its three categories and both `Uncategorized`) rather than a membership predicate: the listing used to `get_or_create` the two `Uncategorized` relations on every call and is now a pure read, pinned by `apps/vod/tests/test_vod_category_list_is_pure_read.py` | G9 | done |``

**I.2 `metrics/curated/defects.yml`**, appended as the last line (substitute `<N>` and `<YYYY-MM-DD>`):

````yaml
- {id: vod-category-list-writes-on-get, title: "GET /api/vod/categories/ get_or_created a movie and a series Uncategorized category, and a relation to each, for every active enable_vod XC account on every call", area: correctness, severity: low, status: fixed, source: null, issue: 490, test: apps/vod/tests/test_vod_category_list_is_pure_read.py, fixed_in: <N>, carried_as: null, first_seen: 2026-09-25, status_changed: <YYYY-MM-DD>}
````

## Appendix J — how the appendices were verified

- Every fix and test above was prototyped in the planner's worktree at `93d1e424`, measured in the private container `fixplan-490-b2`, and reverted; only this document is committed.
- Appendices C–H were produced with `git diff 93d1e424 -- <path>` from the prototype. After this document was written, each fenced block was **extracted from this file** and applied to a fresh `git archive 93d1e424` tree: `git apply --check --whitespace=error` accepted each one alone and all six together; after applying them and copying Appendices A and B out of this file, each of the eight files was byte-identical (`cmp`) to the measured prototype.
- Appendix I.1's old literal occurs once in `git show "93d1e424:e2e/COVERAGE.md"`; I.2 with `<N>` = 999 passed `python3 -m metrics.build --validate-only` (`47 defects`).
- The measured runs: seed baseline (Task 0), red (Task 1), green (Task 2), five break-checks (Task 3), fresh-database labels (Task 4), `tsc` and the guards project (Task 5), before/after images and the exact-three break-check (Task 6).
