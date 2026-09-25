# Fix plan, category I — Hypothesis property tests for the fuzz-hardening surfaces

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Land permanent, deterministic Hypothesis property tests over the provider- and
client-controlled parsing surfaces of `apps/epg`, `apps/m3u`, `apps/output`, `apps/vod` and
`apps/timeshift`. That closes the four duplicate groups of fuzz-hardening issues (sixteen tracker
issues, four survivors). The shrunk counterexamples from those issues and their linked defect issues
ride along as `@example` rows.

**Category.** I: property-based test work items from the domain-fuzz campaign. Eighteen issues are
in the file. Seventeen are four duplicate groups, and #109 is parked by the user (§ Parked).

**Seed SHA: `a54b09a9`** (`main`, 2026-09-23). Every `file:line` below was opened there. Every module
in the appendices was **run** there, in a private test container (`fixplan-I`, bind-mounted at this
plan's worktree, never the shared `dispatcharr-testrunner`). The run was repeated with the category
C and D fixes each module depends on applied by hand, and each module was break-checked. Nothing but
this document is committed.

**Ordering position.** Ninth of ten: B, A, J, C, D, E, G, H, **I**, F. Every PR here is **test-only**
and depends on fixes planned in C (`origin/docs/fixplan-C`, PR #345) and D (`origin/docs/fixplan-D`).
§ Prerequisites names each one, and each PR's Task 0 verifies it merged before anything else runs.

**Architecture.** Django 6 + DRF control plane, Celery, and the Go relay in `relay/`, which is
untouched here. Every module is a `django.test.SimpleTestCase` with no database and no Redis; one uses
an in-module fake Redis. Each module lives in the owning app's `tests/` package, so the PR routes to
that app's backend label and nothing else.

**Tech stack.** Python 3.13, Django 6, Hypothesis `6.165.10`, pinned in `uv.lock:1027-1028` and a
**main** dependency at `pyproject.toml:44` (kept there; see Global constraint 9), and lxml.

**Spec.** There is no phase spec. The inputs are the planner brief (rule 5, the test-modification
rule; rule 6, fuzz branches are reference only), the user's rulings of 2026-09-23 (#109 parked), the
seventeen issue bodies, and the C and D plans named above.

**Planner's worktree.** `.worktrees/fixplan-I`, branch `docs/fixplan-I`. Only this file is committed.

---

## Global constraints

Numbered so a task step can cite one. **A conflict between a constraint and a step is a STOP and
report, never a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's
   cwd is correlated across concurrent agents (`CLAUDE.md` § Repository and direction).
2. **`set -o pipefail`** on any pipeline whose exit status you read. Never `2>/dev/null` a git query
   you interpret. Write `git show "${ref}:path"` with braces. `grep -c` prints `0` and exits 1 on no
   match; where `0` is the PASS, run it bare and read the number.
3. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit with
   `git commit -F <file>`. The commit gate matches on command text.
4. **Test-modification rule (verbatim from the lead).** A test may change only when the behaviour it
   pins is the thing being changed, and every such change is listed in the PR section with its before
   and after assertion. Never widen a tolerance, lower a count or delete an assertion to make a run
   green. New behaviour gets a new test named after the defect. **No PR in this plan changes an
   existing test.** Every PR adds new modules only. Each PR section names the existing label that
   must stay green unmodified.
5. **The appendix modules are the deliverable, verbatim.** Extract them with the script in § Appendix
   extraction. Do not retype them, and do not "improve" a strategy, an `@example` or a filter. Each
   one was measured, and several exist because a weaker draft stayed green under a break-check. If a
   module does not go green on the merged tree, STOP and report the failure line. Never edit the
   module to pass. The fix it waits on is another plan's.
6. **Never delete or weaken an `@example`.** Each `@example` is a shrunk counterexample from an issue
   body, or a case a sibling plan's fix must handle. When one fails, the dependency it names has not
   merged, or merged wrong. That is a STOP.
7. **Test container.** The `PostToolUse` hooks always use the shared container
   `dispatcharr-testrunner`, whose mount decides which tree is tested (`CLAUDE.md` § Test hooks).
   Writing a `tests/test_*.py` file fires the hook against that container's tree, and the hook refuses
   loudly when the tree is not yours. Re-point it only after the occupancy check (`docker ps --filter
   name=dispatcharr-testrunner` plus file mtimes). For runs you launch yourself, prefer a private
   container:
   `DISPATCHARR_TEST_CONTAINER=fix-I-<n> DISPATCHARR_TEST_DB_VOLUME=fix-I-<n>-db CLAUDE_HOOK_REPO_ROOT=<wt> /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh`.
   Run modules and labels with the hook's own environment:

   ```bash
   docker exec -w /repo \
     -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
     -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
     -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
     -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
     fix-I-<n> /dispatcharrpy/bin/python manage.py test <label-or-module> -v1
   ```

   Flush Redis before a whole-label run (`docker exec fix-I-<n> redis-cli flushall`), as the hook and
   CI do. Run each label **once without `--keepdb`** before push (the seeded-row drift trap).
8. **Hypothesis settings are fixed, and every module carries the same block.** It is byte-identical
   to `tests/test_redaction.py:29-32`:

   ```python
   hyp_settings.register_profile(
       "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
   )
   hyp_settings.load_profile("dispatcharr-ci")
   ```

   Why each value, and why this is deterministic and fast enough:
   - **`derandomize=True`.** Each test's random source is seeded from a hash of the test function's
     own source (`hypothesis/core.py:719-720`), so every CI run of an unchanged test draws the same
     examples. A red CI run reproduces locally with the same command. Editing a test changes its
     example set, which is intended. At 6.165.10 `derandomize=True` also **implies `database=None`**
     (`hypothesis/_settings.py:684-690`). (Corrected by #476: `derandomize=True` implies
     `database=None`, so no example database is written, but Hypothesis 6.165.10 still creates
     `.hypothesis/constants/` and `.hypothesis/unicode_data/` on a writable tree (measured: 156
     files, 664K); the directory ships its own `.gitignore` of `*`, so no repository `.gitignore`
     entry is needed; the plan's original "no `.hypothesis/` directory appeared" measurement was
     taken on the read-only `/repo` mount, where the writes fail silently.) What does matter is
     that the hook container mounts `/repo` read-only, so no state carries between runs or between
     CI shards regardless of which of these two directories Hypothesis would otherwise write.
   - **`deadline=None`.** CI containers are loaded. A per-example deadline is a wall-clock assertion
     and would flake. It buys nothing here: none of these helpers has a latency contract.
   - **`max_examples=200`.** This matches the existing module. The whole plan adds 239 tests, 232 of
     them `@given`, and about 35 s of wall time spread across five labels (§ Timings). Each label runs
     in its own CI container, so no job grows by more than about 9 s.
   - **One profile name, one set of values, registered in every module.** `load_profile` is global.
     If two modules registered `dispatcharr-ci` with different values, a one-process run's result
     would depend on import order. Byte-identical registration makes the order irrelevant. Measured:
     the 77 timeshift properties plus `tests.test_redaction` in one process ran 111 tests, OK. A
     shared helper module was rejected: under `dispatcharr/` it would route every PR that touches it
     to all fifteen labels (`_SHARED_PATH_PREFIXES`), and the existing module already inlines the
     block. Each PR's verification step checks the block is identical (Task 3 in each PR).
   - **No health check is suppressed.** None fired in any run. Strategies are bounded with
     `max_size`, and no `assume` or `.filter` discards most draws. If `too_slow` or `filter_too_much`
     fires on CI, STOP and report. Do not add `suppress_health_check`.
9. **`hypothesis` stays in the main dependency list** (`pyproject.toml:44`). CI installs `--no-dev`,
   and a label whose module fails to import reports errors rather than failures (`CLAUDE.md` §
   Testing). No PR here touches `pyproject.toml` or `uv.lock`.
10. **No `metrics/curated/` edit.** None of the seventeen issues has a `defects.yml` row. Checked:
    `grep -cE "issue: ${n}[,} ]" metrics/curated/defects.yml` is `0` for every number. None is a
    CLAUDE.md "Known defects" bullet, an e2e `test.fail()` pin or a parity-matrix row. The dashboard's
    `property_tests` tile (`metrics/curated/catalogue.yml:14`) is collected automatically by
    `scripts/metrics/collect_tests.py:13`, `:108` and moves by itself.
11. **Branch names** are `fix/I-<n>-<slug>`. No PR touches `docker/`, `relay/httpapi/` or
    `docker/nginx.conf`, so none takes the `migration/` prefix.
12. **Nothing under `apps/`, `core/` or `relay/` is edited except by adding the new test modules.**
    The one non-test edit in the whole plan is two sentences of `CLAUDE.md` in I-1.

---

## Prerequisites: what each PR waits on

Every PR in this plan is red on the seed tree **by design**. Its `@example` rows are the
counterexamples that other categories' fixes close. The table lists every dependency, the seed
result, and what the module does once the fix merges.

| PR | depends on | what it must have done | seed result | with the fix |
|---|---|---|---|---|
| I-1 epg | **C-2** (#75, #76/#156, #157) | Adjacent `±hhmm` offset normalised; `_decode_channel_id(raw, quote=b'"', entity_doctype=True)` plus `_xmltv_file_gets_entity_doctype(file_path)` (C Appendix A) | 52 run: 50 OK, 1 FAIL (`#75 -0800`), 1 ERROR (import of `_xmltv_file_gets_entity_doctype`) | 53 OK |
| I-2 m3u | **C-3** (#199, #217, #262), **C-4 as adopted** (#171), **C-5** (#68, #146) | `OverflowError` caught and `_user_info()`; the `m3u_cp1252_fallback` decode; the `regex` filter wrapper; the `$N` rule `\$(0[1-9]\|[1-9]\d?)` (see below); `.casefold()`; both counter repairs | 49 run, the same 10 red in 3 of 3 runs | 49 OK in 3 of 3 runs |
| I-3 output+vod | **C-1, AMENDED** (#90/#211), **C-6** (#242) | Out-of-range captures treated as "no time or date", **with the year bound `2 <= year <= 9998`**, not C-1's `1 <= year <= 9999` (see below); `extract_year` coerces with `str()` | custom dummy: 2 errors; vod provider helpers: 7 errors | 26 + 34 OK |
| I-4 timeshift | **D-3, AMENDED** (#216, #141, #111) | D Appendix C as amended at `b84cc664`: one `_ascii_digits` helper (`isascii() and isdigit()`) guarding every digit run (see below) | 15 of 77 red, all on D-3 mechanisms | 77 OK |

**Two sibling plans had to be amended before this plan can land, and both amendments have landed
in their plans.** Both gaps were found by these modules, measured, and reported to the lead on
2026-09-23.

| plan | head | what it now says | where |
|---|---|---|---|
| C | `8eebb05f` | C-1's bound is `2 <= year <= 9998`; C-4's rule is `\$(0[1-9]\|[1-9]\d?)` | plan C `:154`, `:455`, `:776` at that head |
| D | `b84cc664` | D-3 guards every digit run with one helper, `_ascii_digits(value)`: `value.isascii() and value.isdigit()` | plan D Appendix C.2 at that head |

I re-ran the five timeshift modules on D's final Appendix C, extracted from `b84cc664` with
`git apply`: 77 of 77 passed in three of three runs. D's own break-check for the guard, changing
`_ascii_digits` to `return value.isdigit()`, reddens five ranges properties with
`ValueError: invalid literal for int() with base 10: '²'`.

**This plan assumes both heads as stated.** Each PR's Task 0 checks the fix again against `main`, by
content, never by plan head.

- **C-1's year bound still crashes** (plan C, #90 section, "Fix", Date bullet). With C-1 applied as
  written, two channel names raise `OverflowError`:
  - `Ch 23:30 12/31/9999` in UTC raises `date value out of range` at
    `event_end_utc = event_start_utc + timedelta(minutes=program_duration)` (`apps/output/epg.py:671`,
    and its twin at `:729`).
  - `Ch 0:10 1/1/1` in Asia/Kolkata raises inside pytz `localize` at `apps/output/epg.py:572` (twin at
    `:554`).

  Bounding the year to `2 <= year <= 9998` made the property green, measured. Any tighter window,
  such as 1900 to 2100, would also work. I-3's module carries both names as `@example` rows.
- **D-3's `isdigit()` guards raise on Latin-1 superscript digits** (plan D, Appendix C.2). `'²'`,
  `'³'` and `'¹'` (U+00B2, U+00B3, U+00B9) are `str.isdigit()` true, and `int()` refuses them. At seed
  these inputs are caught by the `try` and return `None`. On D-3 as written they raise `ValueError`:
  `_parse_client_range('bytes=²-')` and `('bytes=0-²')`, `_is_suffix_range('bytes=-²')`, and
  `_parse_content_range_header('bytes ²-5/10')` and `('bytes 0-5/²')`. Hypothesis also found
  `bytes=¹-` unaided. They are reachable because WSGI decodes the client's `Range` header as Latin-1,
  and `requests` decodes the provider's `Content-Range` the same way. Plan D fixed it with one
  helper, `_ascii_digits`, used at every digit check. D also added a U+0663 (Arabic-Indic three)
  example, which it now refuses. This plan's properties are indifferent to that: `None` is a
  permitted answer.

**If either amendment has not landed** when the PR comes up, Task 0 STOPs. The two `@example` rows
are not dropped (Global constraint 6).

**A third seam, C-4's `$N` grammar, was changed by plan C after this plan reported it.** C-4 first
proposed `\$(0*[1-9]\d*)`, which maps `$001` to group 1 and `$012` to group 12. JavaScript's
`String.prototype.replace` reads at most two digits after `$`, and a leading zero only as `$0n`.
**Plan C adopted `\$(0[1-9]|[1-9]\d?)` → `\g<N>`** (lead, 2026-09-23), which is exactly that grammar.
**This plan assumes the adopted rule.**

I-2's backreference module pins it with `test_multi_digit_tokens_read_exactly_as_javascript_does`.
That test runs eight templates on a twelve-group pattern over `abcdefghijkl`, against outputs
recorded from Node 22 on 2026-09-23:

| template | Node 22 output |
|---|---|
| `$012` | `a2` |
| `$001` | `$001` |
| `$0012` | `$0012` |
| `[$100]` | `[j0]` |
| `$12` | `l` |
| `$01` | `a` |
| `$1x` | `ax` |
| `$010` | `a0` |

Measured results:

| rule | result |
|---|---|
| seed | the test fails with NUL and control bytes |
| C-4's first rule | fails on five of the eight rows, e.g. `'l' != 'a2'` on `$012` |
| the adopted rule | green |

The one remaining divergence is not asserted. JavaScript falls back to reading `$10` with two groups
as `$1` followed by `0`, while the helper refuses it; plan C records that as pre-existing. The two
Hypothesis properties and the new test are all indifferent to the user's pending ruling on a bare
`$0`: whole match, or literal.

---

## Files this plan touches

All new, all test modules, except the one `CLAUDE.md` edit. Lines and test counts are for the appendix
text.

| file | PR | lines | tests |
|---|---|---|---|
| `apps/epg/tests/test_property_xmltv_time.py` | I-1 | 138 | 5 |
| `apps/epg/tests/test_property_programme_index.py` | I-1 | 242 | 10 |
| `apps/epg/tests/test_property_channel_id_parity.py` | I-1 | 142 | 2 |
| `apps/epg/tests/test_property_programme_metadata.py` | I-1 | 387 | 17 |
| `apps/epg/tests/test_property_text_query.py` | I-1 | 112 | 5 |
| `apps/epg/tests/test_property_sd_helpers.py` | I-1 | 246 | 14 |
| `CLAUDE.md` (§ Testing, one sentence) | I-1 | — | — |
| `apps/m3u/tests/test_property_m3u_parsing.py` | I-2 | 261 | 14 |
| `apps/m3u/tests/test_property_backreferences.py` | I-2 | 160 | 3 |
| `apps/m3u/tests/test_property_credentials.py` | I-2 | 123 | 6 |
| `apps/m3u/tests/test_property_numbering.py` | I-2 | 135 | 9 |
| `apps/m3u/tests/test_property_stream_filters.py` | I-2 | 77 | 3 |
| `apps/m3u/tests/test_property_connection_pool.py` | I-2 | 175 | 5 |
| `apps/m3u/tests/test_property_db_retry.py` | I-2 | 75 | 2 |
| `apps/m3u/tests/test_property_xc_account_values.py` | I-2 | 146 | 7 |
| `apps/output/tests/test_property_epg_export_helpers.py` | I-3 | 150 | 5 |
| `apps/output/tests/test_property_custom_dummy_programs.py` | I-3 | 171 | 3 |
| `apps/output/tests/test_property_output_formatting.py` | I-3 | 190 | 18 |
| `apps/vod/tests/test_property_image_proxy.py` | I-3 | 294 | 10 |
| `apps/vod/tests/test_property_provider_helpers.py` | I-3 | 308 | 24 |
| `apps/timeshift/tests/test_property_timestamps.py` | I-4 | 320 | 20 |
| `apps/timeshift/tests/test_property_url_builders.py` | I-4 | 170 | 8 |
| `apps/timeshift/tests/test_property_ranges.py` | I-4 | 345 | 23 |
| `apps/timeshift/tests/test_property_pool_decisions.py` | I-4 | 262 | 12 |
| `apps/timeshift/tests/test_property_stats.py` | I-4 | 248 | 14 |

## Overlap with other categories

Checked against `sweep-report.md` and every category's issue file. The four PRs add files nobody else
touches, so no textual collision is possible. Every overlap below is **semantic**: another plan
changes a helper whose contract a property asserts.

| file under test | other plan and what it does there | who goes first | risk |
|---|---|---|---|
| `apps/epg/tasks.py` (`parse_xmltv_time`, `_decode_channel_id`, offset helpers) | **C-2**: adjacent offsets, skip malformed timestamps in the offset helpers, new `_decode_channel_id` signature | C | Semantic, by design. I-1's parity module imports C-2's new helper and fails on import without it. `parse_xmltv_time` keeps raising `ValueError`, as C-2 requires. I-1 asserts exactly that and does not change it. |
| `apps/m3u/models.py`, `apps/m3u/tasks.py`, `apps/m3u/utils.py`, `apps/m3u/connection_pool.py` | **C-3, C-4, C-5** (listed in § Prerequisites). **B-5** (#61) edits `collect_xc_streams`; **E** #56/#60/#70 edit the group-refresh lock, the refresh message at `:3502-3514` and the auto-sync SUCCESS at `:3891`. | B, C, E | None for B and E: no property exercises those functions. The functions I-2 tests (`_batch_stream_count_message`, `_parse_batch_stream_counts` at `:1070`, `:1077`) are not E's `:3502-3514` message. Task 0 greps them still exist. |
| `apps/output/epg.py` (`generate_custom_dummy_programs`) | **C-1**, which must be amended (§ Prerequisites) | C | Semantic, by design. |
| `apps/output/views.py` (`format_duration_hms` at `:1778`) | **B-2** (`:357-560`), **C-1** (`:785-940`), **D-4** (`:1674-1705`), **E** #80/#85 (`:305-306`, `:593`) | all before I | None. No other plan edits `format_duration_hms`. |
| `apps/vod/tasks.py` (`extract_year` and siblings) | **C-6** (#242) | C | Semantic, by design. |
| `apps/timeshift/views.py`, `helpers.py`, `stats.py` | **D-3**, which must be amended (§ Prerequisites). **G** #183 sanitises one log line (`views.py:3256-3264`). **B-5** cites `helpers.py:424-432` for comparison only. | D, G | Semantic, by design for D. None for G and B: no property reads log text or `collect_xc_streams`. |
| `core/xtream_codes.py` (`normalize_server_url`), `core/utils.py` (`custom_properties_as_dict`) | **A** #233 (`core/utils.py:890-924`), **G** #81 (`core/utils.py:1012`) | A, G | None. Different functions. **Routing note**: these two `core/` helpers get property coverage from `apps.m3u.tests` and `apps.output.tests`, but a `core/` edit routes through `_SHARED_PATH_PREFIXES` to every label anyway, so they still run. |
| `CLAUDE.md` | **J-1, J-2, J-3** each edit other sentences | J | None. I-1 edits one sentence in § Testing that no J section names. |

---

## Duplicates and survivors

The lead closes the rest of each group. Each survivor is the issue whose scope the PR matches
closest. Every duplicate's surfaces are covered by the same PR (§ Coverage table).

| group | survivor | duplicates | why this one |
|---|---|---|---|
| epg | **#202** | #274, #158, #74 | Its scope is the union: the XMLTV parser, metadata extraction and the SD helpers. Its own body already "Closes #158". |
| timeshift | **#192** | #260, #142, #215, #55 | The widest single body: helpers, range parsers and stats. #215 and #142 cover subsets of views, and #55's branch is stale (base `8e567f4e`). |
| m3u | **#218** | #145, #200, #69 | The title names the domain generically ("M3U parsing and numbering surfaces"). The PR covers #145's filters and counters, #200's `exp_date` and URL normalisation, and #69's credentials and retry under it. |
| output + vod | **#92** | #210, #162, #243 | The only title naming both apps, `test(output,vod)`, which matches the one PR over both labels. #243's vod-helper scope lands in the same PR. |

---

## Per-issue analysis

These are test-work issues, not defects. The "root cause" for all seventeen is the same, and was
verified at seed: no `test_property_*` module exists under `apps/` (`find apps -name
'test_property_*'` prints nothing), and `tests/test_redaction.py` is the tree's only `@given` module.
The fuzz branches the issues name were never merged, and per brief rule 6 they are **reference only**.
Every module in the appendices was written fresh against the seed helpers, and every invariant was
re-derived from the seed code. Where a reference property was weak, wrong or pinned a defect, the
difference is named below.

### epg: #202 (survivor), #274, #158, #74 — PR I-1

- **Surfaces, all present at seed, none dropped.**
  - `apps/epg/tasks.py`: `_parse_programme_element` `:242`, `_PrependStream` `:249`,
    `_open_xmltv_file` `:290`, `validate_icon_url_fast` `:325`, `parse_xmltv_time` `:2504`,
    `extract_custom_properties` `:2547`, `detect_file_format` `:2787`, `_CHANNEL_ATTR_RE` `:2894`,
    `_decode_channel_id` `:2902`, `_find_programme_tag` `:2910`, `_programme_to_dict` `:2939`.
  - `apps/epg/utils.py`: `sd_poster_cache_bust` `:32`, `sd_poster_proxy_path` `:44`,
    `extract_season_episode_from_description` `:58`, `extract_season_episode` `:76`.
  - `apps/epg/query_utils.py`: `parse_text_query` `:35`.
  - `apps/epg/sd_utils.py`: `sd_auth_lockout_seconds_for_code` `:81`, `sd_credential_fingerprint`
    `:109`, `sd_auth_failure_message` `:209`, `sd_token_response_code` `:266`,
    `sd_parse_response_payload` `:691`.
  - `apps/epg/sd_tasks.py`: `_sd_pick_poster_url` `:220`.
- **Regression examples carried.**
  - #75: `20260728183000+0530` and `-0800`.
  - #76: `+2400`; #156: `+2460`. These sit on the "raises only `ValueError`" property, because
    `parse_xmltv_time` keeps raising under C-2.
  - #157: all six rows of C-2's table, plus the two ids existing tests pin
    (`test_programme_index.py:170`, `:406`).
- **Where the reference was wrong.** #274 recorded `parse_text_query`'s behaviour around case-growing
  characters as "parser behaviour". It is a defect that raises `IndexError` (finding F-1 below). The
  module keeps the no-raise property to length-preserving text, with a comment naming the finding.
- **Tests.** Six new modules, 53 tests. Existing tests changed: none.
- **Size** L (1,267 lines, all test). **Upstreamable** no: the parity module needs C-2's fork-side
  signature. The other five would apply to upstream `dev` once C-2 is upstreamed.

### m3u: #218 (survivor), #145, #200, #69 — PR I-2

- **Surfaces, all present at seed.**
  - `apps/m3u/tasks.py`: `_db_query_with_retry` `:80`, `_open_m3u_text_source` `:169`,
    `get_case_insensitive_attr` `:590`, `parse_extinf_line` `:598`, `iter_m3u_entries` `:644`,
    `_compile_m3u_stream_filters` `:1017`, `_stream_passes_m3u_filters` `:1030`,
    `_batch_stream_count_message` `:1070`, `_parse_batch_stream_counts` `:1077`,
    `_next_available_number` `:1907`, `_pick_target_number` `:1927`.
  - `apps/m3u/utils.py`: `convert_js_numbered_backreferences` `:13`, `parse_is_adult` `:25`,
    `normalize_stream_url` `:37`.
  - `apps/m3u/connection_pool.py`: `compute_credential_fingerprint` `:49`,
    `extract_credentials_from_stream_url` `:57`, `_safe_decr` `:232`, reserve `:261`, `:280`, release
    `:316`.
  - `apps/m3u/models.py`: `M3UAccountProfile._parse_exp_date` `:307`,
    `_parse_exp_date_from_custom_properties` `:323`.
  - `core/xtream_codes.py`: `normalize_server_url` `:9`.
- **Regression examples carried.**
  - #199: the 24-digit string, `"1e30"`, `inf`, `"-1e20"`, and a non-dict `user_info`.
  - #146: `start=-1` (shrunk) and `-3` with `max_streams=1`.
  - #68: `'µ'` against its `.upper()`. #69's branch shrank to `'μ'`.
  - #171: `$0` on `(.*)$` over `"/"`, `$01/$2` and `$02-$01`.
  - #217: a Latin-1 `TF1 Séries HD` line.
- **Where the references were wrong, and what replaced them.**
  - #145's "a pre-negative `_safe_decr` key is left untouched" pinned the #146 defect. It is replaced
    by the post-C-5 "never below zero, and repaired" property.
  - #200's `_could_be_out_of_range_number` filter hid #199. It is removed, so totality now covers
    every JSON scalar.
  - #218's ASCII-only fingerprint restriction is replaced by a Unicode caseless-domain property,
    post-C-5. The domain filter `u.upper().casefold() == u.casefold()` touches the inputs only; the
    assertion is on the fingerprint.
  - The credential-slot conservation property is restricted to **one stream per profile**. Two
    streams expose finding F-4, a real and unfiled leak. The restriction is in the docstring and
    is widened once F-4 is fixed.
- **Not covered, by design.** `transform_url` (`apps/proxy/next_source.py`) belongs to the
  `apps.proxy.tests` label, and C-4 pins it with example tests. The shared helper's property covers
  the rule it now calls.
- **Tests.** Eight new modules, 49 tests. Existing tests changed: none.
- **Size** L (1,152 lines). **Upstreamable** no: it depends on C-3, C-4 and C-5, and C-4 is not
  upstreamable (plan C).

### output + vod: #92 (survivor), #210, #162, #243 — PR I-3

- **Surfaces, all present at seed.**
  - `apps/output/epg.py`: `_programme_overlaps_export_window` `:34`, `_ceil_to_half_hour` `:42`,
    `generate_fallback_programs` `:83`, `generate_custom_dummy_programs` `:258`.
  - `apps/output/views.py`: `format_duration_hms` `:1778`.
  - `apps/output/streaming_chunk_cache.py`: `_decode_chunk` `:36`, `_encode_chunk` `:44`.
  - `apps/channels/utils.py`: `coerce_channel_profile_ids` `:22`, `format_channel_number` `:46`.
  - `core/utils.py`: `custom_properties_as_dict` `:79`, `ensure_custom_properties_dict` `:105`.
  - `apps/vod/image_proxy.py`: `is_proxyable_image_url` `:22`, `_as_backdrop_list` `:29`,
    `get_relation_artwork` `:39`, `prefer_relation_artwork` `:88`, `_url_from_props` `:136`,
    `format_vod_image_url` `:199`, `rewrite_backdrop_paths` `:220`.
  - `apps/vod/tasks.py`: `extract_duration_from_data` `:1165`, `normalize_rating` `:1193`,
    `extract_year` `:1220`, `extract_year_from_title` `:1230`, `parse_date` `:1307`,
    `is_non_empty_string` `:2106`, `extract_string_from_array_or_string` `:2114`,
    `clean_custom_properties` `:2132`, `should_update_field` `:2163`, `is_blank_vod_value` `:2177`.
- **Regression examples carried.**
  - #90 and #211: `Team A @ 10:75`, `Ch 10:99`, `C 10:99999999999999999999`, `Game 2/31 @ 10:30`.
  - C-1's own `X 13:30pm` and years `0` and `99999`.
  - The two C-1-amendment names above.
  - #242: `1` (shrunk), `2011`, `[2011]`, `2011.5`, `True`, with C-6's expected values.
- **Where the references were weak, and what replaced them.**
  - #92's `is_proxyable_image_url` test checked one direction of the implication. It is replaced by
    exact equality with an independent three-prefix oracle, plus security `@example`s: `HTTP://`,
    `file:///etc/passwd`, `//evil`, `data:`, `javascript:`.
  - #92's `rewrite_backdrop_paths` property stayed green under a wrong-index break-check, because its
    strategy almost never drew a proxyable URL past index 0. The strategy is strengthened, with an
    explicit `@example`.
  - #243's never-raises property drew random dict keys and so rarely reached `duration_secs`. That is
    why it missed finding F-6.
  - `extract_year`'s strategy is widened from strings to every JSON value, as #242 asks.
- **Not a property target.** #91 is a view's query parameter (`apps/output/views.py:881`). C-1 pins it
  with example tests.
- **Tests.** Five new modules, 60 tests. Existing tests changed: none.
- **Size** L (1,113 lines). **Upstreamable** no: `generate_custom_dummy_programs` is fork-only (plan C,
  #90).

### timeshift: #192 (survivor), #260, #142, #215, #55 — PR I-4

- **Surfaces, all present at seed.**
  - `apps/timeshift/helpers.py` `:46-566`: timestamp normalisation and parsing,
    `convert_timestamp_to_provider_tz`, `client_duration_to_window`, `resolve_catchup_duration`,
    `programme_age_days`, `order_catchup_streams_for_timestamp`, the two URL formats,
    `build_timeshift_candidate_urls`, `client_timeshift_url_layout`, `format_timestamp_as_*`.
  - `apps/timeshift/views.py`:
    - the Range helpers `:1103-1260`, `:1303`, `:1353`, `:1946-1979`;
    - the pool predicates `:807`, `:831`, `:1245`, `:1318`, `:1336`, `:1536`, `:1705`, `:1935`,
      `:2001`.
  - `apps/timeshift/stats.py`: `:47`, `:124`, `:130`, `:146`, `:219`, `:296`.
  - `apps/timeshift/redis_keys.py`: `:73`, `:88`.
- **Written against the post-D-3 contracts.** `_parse_client_range("bytes=-500")` is `None`, and so
  is an inverted range. `_parse_content_range_header` refuses `end < start` and `end >= total`.
  `is_near_eof_offset` and `_is_suffix_range` are new. `convert_timestamp_to_provider_tz` keeps
  nonzero seconds.
- **Regression examples carried.**
  - #141: `bytes=-500`, `bytes=100-50`, and the upstream `bytes 100-50/1000`.
  - #216: a 1.5 MiB archive at `512000` and `1048576`.
  - #111: `2026-01-15 12:00:45` in Europe/Brussels.
  - The D-3-amendment superscripts: `bytes=²-`, `bytes=0-²`, `bytes=-²`, `bytes ²-5/10`,
    `bytes 0-5/²`.
- **Dropped or narrowed, each with a comment in the module.**
  - `mint_session_id`, `programme_media_id` and `virtual_channel_id` are plain f-string builders that
    no issue names.
  - `get_programme_duration`'s DB branch needs the ORM.
  - The reference's `a6_stats` imported the deleted `apps.proxy.live_proxy.constants`. The module
    uses `apps.proxy.constants`.
  - #54 was ruled invalid: its "position freezes at 0" came from a generator drawing
    `position_anchor_at=0.0`. The stats strategies draw realistic epoch anchors (1e9 to 1e10) and cite
    #54.
  - Timestamp instants are drawn from 1900 to 2100, with a comment naming finding F-5.
  - The arbitrary-text strategy `timestamp_text` excludes both of F-5's input shapes:
    - Unicode category No, where `²` lives;
    - an ISO string starting with year `0001` or `9999`.

    Before review round 1 it drew from all text, and passed only because the derandomized draw
    missed those shapes (reviewer's finding). The exclusion is now explicit and commented, and
    widening it is part of F-5's fix.
- **Tests.** Five new modules, 77 tests. Existing tests changed: none.
- **Size** L (1,345 lines). **Upstreamable** no: it depends on D-3 plus the amendment. D-3 itself is
  upstreamable (plan D), so this would follow it.

---

## Parked

**#109** ("[aw] Domain fuzz campaign failed"): parked by the user on 2026-09-23 ("IGNORE for now. No
memo, no plan"). The workflow is `disabled_manually`. No memo and no PR section. The ledger records it
as parked.

---

## PR sections, in implementation order

The order follows the dependencies: C merges before D, so the three C-dependent PRs go first. Within C,
C-2 is the earliest plan section, which puts epg first. Each PR is independent of the other three, so
any may slip without blocking the rest.

Every PR has the same five tasks: prerequisites, extract, prove the seams, break-check, then the
label, the profile check and push. Only the specifics differ, and each section spells them out in full.

### Appendix extraction (used by every PR's Task 1)

Each appendix module sits under a line `<!-- file: <repo-relative path> -->`, followed by one fenced
`python` block. This script writes the named files for one PR and nothing else:

```bash
cd <your worktree> && python3 - <plan-path> <path-prefix> <<'PY'
import re, sys, pathlib
plan, prefix = sys.argv[1], sys.argv[2]
text = pathlib.Path(plan).read_text()
pat = re.compile(r"<!-- file: (\S+) -->\n```python\n(.*?)\n```\n", re.S)
n = 0
for path, body in pat.findall(text):
    if path.startswith(prefix):
        pathlib.Path(path).write_text(body + "\n")
        print(f"{path}: {body.count(chr(10)) + 1} lines")
        n += 1
print(f"{n} files written")
PY
```

Pass `apps/epg/tests/`, `apps/m3u/tests/`, `apps/output/tests/` then `apps/vod/tests/`, or
`apps/timeshift/tests/`. The printed line counts must equal § Files this plan touches. Writing the files
this way does not fire the `PostToolUse` hook, which only watches the Write and Edit tools. The commit
gate still runs the label on commit.

---

### PR I-1: `fix/I-1-epg-property-tests`

- **Closes** #202, and duplicates #274, #158, #74.
- **Depends on** C-2.
- **Files** the six `apps/epg/tests/test_property_*.py` modules (Appendix A) and `CLAUDE.md`.
- **Labels** `apps.epg.tests`. `CLAUDE.md` routes to no label
  (`scripts/ci_backend_test_labels.py CLAUDE.md` prints `[]`).
- **upstreamable** no. **Size** L.

#### Task 0: prerequisites

- [ ] **Step 1.** Confirm C-2 merged. Each command below must print at least `1`:

  ```bash
  cd <wt> && grep -c 'def _xmltv_file_gets_entity_doctype' apps/epg/tasks.py
  cd <wt> && grep -c 'entity_doctype=True' apps/epg/tasks.py
  ```

  Both print `0` at seed (checked). For C-2's #75 half, probe the behaviour rather than its spelling,
  inside the test container (Global constraint 7's `docker exec` prefix):

  ```bash
  ... /dispatcharrpy/bin/python manage.py shell -c "from apps.epg.tasks import parse_xmltv_time; print(parse_xmltv_time('20260728183000+0530'))"
  ```

  It must print `2026-07-28 13:00:00+00:00`. At seed it prints `2026-07-28 18:30:00+00:00`. If C-2
  has not merged, STOP.

#### Task 1: extract and run

- [ ] **Step 1.** Branch off current `main`: `git switch -c fix/I-1-epg-property-tests origin/main`.
- [ ] **Step 2.** Run the extraction script with prefix `apps/epg/tests/`. It must print six files,
  with 138, 242, 142, 387, 112 and 246 lines.
- [ ] **Step 3.** Run the six modules together, three times:
  `manage.py test apps.epg.tests.test_property_xmltv_time apps.epg.tests.test_property_programme_index apps.epg.tests.test_property_channel_id_parity apps.epg.tests.test_property_programme_metadata apps.epg.tests.test_property_text_query apps.epg.tests.test_property_sd_helpers`.
  Expected: `Ran 53 tests`, `OK`, identical each time, about 8 s of wall time.

#### Task 2: prove the seams (each edit is reverted)

Each step makes one edit that undoes part of C-2, runs the named module, confirms the failure, then
reverts with `git checkout -- apps/epg/tasks.py`.

- [ ] **Step 1 (#75).** Delete C-2's adjacent-offset space insertion. Expect
  `test_an_adjacent_offset_is_the_same_instant_as_the_spaced_form` to FAIL on its `-0800` `@example`
  with `datetime(2026, 7, 28, 18, 30, tzinfo=...) != datetime(2026, 7, 29, 2, 30, tzinfo=...)`.
- [ ] **Step 2 (#157).** Make `_decode_channel_id` ignore `entity_doctype`, always prefixing the
  DOCTYPE. Expect `test_the_index_key_equals_the_value_lxml_stores` to FAIL with `'aéb' != 'ab'`.
- [ ] **Step 3 (#76 and #156).** No edit. The `+2400` and `+2460` `@example`s pass on the unchanged
  tree, which is the point: `parse_xmltv_time` still raises only `ValueError`. Record that
  `test_out_of_range_offsets_keep_raising_value_error` passes.

#### Task 3: break-checks, one per module (each reverted)

| module | wrong edit | expected failure |
|---|---|---|
| xmltv_time | flip the sign of `-` offset minutes (`apps/epg/tasks.py`, the `-` arm near `:2524`) | spaced-offset property: `datetime(1970, 12, 31, 23, 59) != datetime(1971, 1, 1, 0, 1)` |
| programme_index | drop `'/'` from `_TAG_FOLLOW` (`:2897`) | `test_finds_the_first_real_start_tag_and_its_closing_bracket`: `-1 != 0` |
| programme_index | `_PrependStream`: at the prefix/body boundary read `size - remaining + 1` (`:278`) | `3 not less than or equal to 2` |
| channel_id_parity | as Task 2 Step 2 | `'aéb' != 'ab'` |
| programme_metadata | drop the `+ 1` on the `xmltv_ns` season (`apps/epg/tasks.py:2571`) | the one-based property: `0 != 1` |
| text_query | fold every operator with `&` (`apps/epg/query_utils.py:132-134`, the `op == '&'` choice) | binary-operator property: `'AND' != 'OR'` |
| sd_helpers | stop stripping the password in `sd_credential_fingerprint` (`apps/epg/sd_utils.py:116`) | whitespace property: a hex mismatch |

- [ ] **Step 1.** Make each edit, run its module, and paste the failure line into the PR description.
  A failure that is an `ImportError` or names a different mechanism is not a pass. Revert, then
  confirm `git diff --stat -- apps/epg` is empty.

#### Task 4: CLAUDE.md, the label, the profile check, and push

- [ ] **Step 1.** Replace the sentence in `CLAUDE.md` § Testing that begins
  `**\`tests/test_redaction.py\` is now the only \`@given\` module in the tree**`. The anchor must
  occur exactly once. Before:

  > **`tests/test_redaction.py` is now the only `@given` module in the tree**, and it is what keeps
  > `hypothesis` (with `coverage`) in the **main** dependency list rather than a dev group.

  After:

  > **`tests/test_redaction.py` and the per-app `apps/<app>/tests/test_property_*.py` modules are the
  > tree's `@given` modules**, all registering one byte-identical `dispatcharr-ci` profile
  > (`max_examples=200, derandomize=True, deadline=None`; `derandomize` implies no example database,
  > so nothing is written to the read-only `/repo` mount), and they are what keep `hypothesis` (with
  > `coverage`) in the **main** dependency list rather than a dev group.

  The rest of that paragraph stays as it is. It reads as true before the later I PRs land, because it
  names the pattern, not a count.
- [ ] **Step 2.** Profile check. The command below must print exactly one line, with a count equal to
  the number of `@given` modules in the tree plus `tests/test_redaction.py`: here `7`.

  ```bash
  cd <wt> && for f in tests/test_redaction.py apps/*/tests/test_property_*.py; do grep -A2 'hyp_settings.register_profile(' "$f" | md5sum; done | sort | uniq -c
  ```

- [ ] **Step 3.** `redis-cli flushall`, then run `apps.epg.tests` whole, with `--keepdb` and once
  without it. Expected: OK, with the seed's 295 tests plus C-2's additions plus 53. No existing test
  changes.
- [ ] **Step 4.** Also run `tests.test_redaction` together with the six modules in one process. It
  must be OK, which confirms the registration order does not matter.
- [ ] **Step 5.** Commit: `git add` in one call, then `git commit -F <msgfile>` in another. Push and
  open a **draft** PR with the description below.

#### PR description draft

> **test(epg): Hypothesis property tests for the XMLTV, programme-index, metadata, search and Schedules Direct helpers (#202)**
>
> Six `SimpleTestCase` modules, 53 tests, about 8 s. No DB or Redis. The CI profile is identical to
> `tests/test_redaction.py`'s: derandomized, 200 examples, no deadline. The surfaces are every helper
> #202, #274, #158 and #74 named. The invariants were re-derived from the code, and the fuzz
> branches were used as reference only.
>
> The shrunk counterexamples ride along as `@example`s: #75's adjacent offsets, #76's and #156's
> `+2400` and `+2460`, and every row of #157's channel-id table. C-2 fixed those defects; this pins
> them. The `_decode_channel_id` parity property's oracle is lxml's own parse of a real file, which
> the byte-level path never calls.
>
> Break-checks: <paste one line per module>. Seams: <paste Task 2's two failure lines>.
>
> Not asserted, filed separately: `parse_text_query` raises `IndexError` on `ß a AND b`, so the
> no-raise property draws length-preserving text only, with a comment. One oversized
> `<programme` start tag drops the rest of that 8 MiB read from the index.
>
> Closes #202, #274, #158 and #74. No existing test changed. `CLAUDE.md`'s "only `@given` module"
> sentence is updated.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

### PR I-2: `fix/I-2-m3u-property-tests`

- **Closes** #218, and duplicates #145, #200, #69.
- **Depends on** C-3, C-4, C-5.
- **Files** the eight `apps/m3u/tests/test_property_*.py` modules (Appendix B).
- **Labels** `apps.m3u.tests`.
- **upstreamable** no. **Size** L.

#### Task 0: prerequisites

- [ ] **Step 1.** Each command below must print at least `1`:

  ```bash
  cd <wt> && grep -c 'OverflowError' apps/m3u/models.py                       # C-3 #199
  cd <wt> && grep -c 'm3u_cp1252_fallback' apps/m3u/utils.py apps/m3u/tasks.py # C-3 #217
  cd <wt> && grep -c '_BoundedFilterPattern' apps/m3u/tasks.py                 # C-3 #262
  cd <wt> && grep -c 'g<' apps/m3u/utils.py                                    # C-4 #171 (either ruling emits \g<N>)
  cd <wt> && grep -c 'casefold()' apps/m3u/connection_pool.py                  # C-5 #68
  ```

  Every grep above prints `0` at seed (checked), so each one detects its fix. Then read `_safe_decr` and the reserve path in `apps/m3u/connection_pool.py`, and confirm C-5
  Appendix C's two repairs are present. If any are missing, STOP.

#### Task 1: extract and run

- [ ] **Step 1.** `git switch -c fix/I-2-m3u-property-tests origin/main`.
- [ ] **Step 2.** Run the extraction script with prefix `apps/m3u/tests/`. It must print eight files,
  with 261, 160, 123, 135, 77, 175, 75 and 146 lines.
- [ ] **Step 3.** Run the eight modules together, three times. Expected: `Ran 49 tests`, `OK`,
  identical each time, about 6 to 7 s of wall time.

#### Task 2: prove the seams (each edit is reverted)

| fix undone | edit | expected failure |
|---|---|---|
| C-3 #217 | `errors="strict"` at the plain-text `open(...)` in `_open_m3u_text_source` | `test_arbitrary_playlist_bytes_never_raise_on_any_compression`: `UnicodeDecodeError ... byte 0xe9` |
| C-4 #171 | restore `convert_js_numbered_backreferences` to `regex.sub(r"\$(\d+)", r"\\\1", replacement)` | `test_conversion_never_introduces_a_character_absent_from_target_and_template`: `'\x00\x00'`, a NUL outside target and template |
| C-5 #68 | `.casefold()` back to `.lower()` | `test_case_and_surrounding_whitespace_variants_of_a_username_share_a_fingerprint`: two digests for `'µ'` |
| C-5 #146 | keep the `_safe_decr` repair, drop the reserve repair | `test_the_credential_cap_holds_whatever_the_counter_drifted_to`: `4 != 1` (start `-3`, `max_streams=1`), C-5's own break-check (a) |
| C-3 #199 | remove `OverflowError` from `_parse_exp_date`'s tuple | `test_exp_date_parsing_is_total_over_provider_json`: `OverflowError: timestamp out of range for platform time_t` |

- [ ] **Step 1.** Run each row, paste the line, revert, and confirm `git diff --stat -- apps/m3u core`
  is empty.

#### Task 3: break-checks, one per module (each reverted)

| module | wrong edit | expected failure |
|---|---|---|
| m3u_parsing | `parse_extinf_line`: `attrs[match.group(1)]`, dropping `.lower()` | `test_generated_attributes_and_display_name_round_trip`: `{'A': ''} != {'a': ''}` |
| backreferences | C-4's first-draft rule `\$(0*[1-9]\d*)` in place of the adopted one | `test_multi_digit_tokens_read_exactly_as_javascript_does` (template `$012`): `'l' != 'a2'` |
| credentials | drop the username `.strip()` | whitespace-variant property: digests differ for `username='0'` padded |
| numbering | delete `_next_available_number`'s post-loop `if end is not None and n > end: return None` | `0 != None` (`used=set(), start=0, end=-1`) |
| stream_filters | swap the `url` and `group` target selection in `_stream_passes_m3u_filters` | first-match property: `False != True` |
| connection_pool | as the C-5 #146 seam row | `4 != 1` |
| db_retry | `if attempt + 1 > max_retries` (off by one) | `OperationalError not raised` (`max_retries=1`) |
| xc_account_values | as the C-3 #199 seam row | `OverflowError: timestamp out of range for platform time_t` |

- [ ] **Step 1.** Run each, paste the lines, revert, and confirm the diff is empty.

#### Task 4: the label, the profile check, and push

- [ ] **Step 1.** Profile check (I-1 Task 4 Step 2). The count grows by 8.
- [ ] **Step 2.** `redis-cli flushall`, then run `apps.m3u.tests` whole, with and without `--keepdb`.
  Expected: OK, with the seed's 164 plus C-3, C-4 and C-5's additions plus 49.
- [ ] **Step 3.** Commit in two calls, push, and open a draft PR.

#### PR description draft

> **test(m3u): Hypothesis property tests for M3U parsing, numbering, filters, credentials, pool counters and XC account values (#218)**
>
> Eight `SimpleTestCase` modules, 49 tests, about 6 s, under the shared derandomized profile. The
> connection-pool properties run against an in-module fake Redis.
>
> The counterexamples of the defects C-3, C-4 and C-5 fixed are `@example`s: #199's out-of-range
> `exp_date` values and non-dict `user_info`, #217's Latin-1 playlist, #171's `$0` and `$01`, #68's
> `µ`, and #146's `-1` and `-3`.
>
> The backreference properties do not depend on how the user rules on `$0`. They assert that no
> output character is absent from both the target and the template, and that the output equals a
> hand-written model of JavaScript's `String.prototype.replace` for `$N` tokens with N ≥ 1. C-4's
> adopted `\$(0[1-9]|[1-9]\d?)` grammar is pinned separately against eight outputs recorded from
> Node 22 (`$012` → `a2`, `$001` stays literal, `[$100]` → `[j0]`).
>
> Reference-branch properties that pinned defects were dropped:
> - #145's "a negative counter stays negative";
> - #200's overflow filter.
>
> Not asserted, filed separately: a second stream on one pooled profile leaks a shared credential
> slot. The conservation property holds one stream per profile until that is fixed.
>
> Break-checks: <paste>. Seams: <paste>. Closes #218, #145, #200 and #69. No existing test changed.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

### PR I-3: `fix/I-3-output-vod-property-tests`

- **Closes** #92, and duplicates #210, #162, #243.
- **Depends on** C-1 **amended** and C-6.
- **Files** three `apps/output/tests/test_property_*.py` and two `apps/vod/tests/test_property_*.py`
  modules (Appendix C).
- **Labels** `apps.output.tests` and `apps.vod.tests`. `apps/vod/` routes to both through
  `_PATH_ALIASES`, measured with `scripts/ci_backend_test_labels.py`.
- **upstreamable** no. **Size** L.

#### Task 0: prerequisites

- [ ] **Step 1.** C-6: `grep -c "str(date_string)" apps/vod/tasks.py` prints at least `1`. It prints
  `0` at seed (checked).
- [ ] **Step 2.** C-1: `grep -c 'Invalid time values' apps/output/epg.py` prints at least `1`. It
  prints `0` at seed (checked).
- [ ] **Step 3.** C-1's amendment: read the date condition in `generate_custom_dummy_programs`. The
  year bound must exclude `1` and `9999`, for example `2 <= year <= 9998`. If it reads
  `1 <= year <= 9999`, STOP: the two edge-year `@example`s will fail with `OverflowError`
  (§ Prerequisites), and they stay.

#### Task 1: extract and run

- [ ] **Step 1.** `git switch -c fix/I-3-output-vod-property-tests origin/main`.
- [ ] **Step 2.** Extract with prefix `apps/output/tests/`, which gives three files of 150, 171 and
  190 lines. Then extract with `apps/vod/tests/`, which gives two files of 294 and 308.
- [ ] **Step 3.** Run the five modules together, three times. Expected: `Ran 60 tests`, `OK`,
  identical each time, about 12 s in total.

#### Task 2: prove the seams (each edit is reverted)

| fix undone | edit | expected failure |
|---|---|---|
| C-1 #90 | remove `0 <= minute <= 59` from the time check | custom-dummy property: `ValueError: minute must be in 0..59` and `OverflowError: Python int too large to convert to C int` |
| C-1 amendment | year bound back to `1 <= year <= 9999` | custom-dummy property: `OverflowError: date value out of range` on `Ch 23:30 12/31/9999` |
| C-6 #242 | `int(date_string.split('-')[0])` (drop `str()`) | three `extract_year` tests: `AttributeError: 'int' object has no attribute 'split'` |

- [ ] **Step 1.** Run each row, paste the line, revert, and confirm
  `git diff --stat -- apps/output apps/vod apps/channels core` is empty.

#### Task 3: break-checks, one per module (each reverted)

| module | wrong edit | expected failure |
|---|---|---|
| epg_export_helpers | `end_time < lookback_cutoff` becomes `<=` (`apps/output/epg.py:35`) | overlap property on its explicit example: `False != True` |
| custom_dummy_programs | as the C-1 #90 seam row | `ValueError: minute must be in 0..59` |
| output_formatting | `(seconds % 3600) // 60` becomes `seconds // 60` in `format_duration_hms` (`apps/output/views.py:1783`) | `Tuples differ: (4, 2) != (2, 2)` |
| image_proxy | `url.startswith` becomes `url.lower().startswith` (`apps/vod/image_proxy.py:26`) | allowlist property, on the `HTTP://` example: `True is not False` |
| provider_helpers | `should_update_field` returns `new_string is not None` (`apps/vod/tasks.py:2174`) | `True is not False` |

- [ ] **Step 1.** Run each, paste the lines, revert, and confirm the diff is empty.

#### Task 4: the labels, the profile check, and push

- [ ] **Step 1.** Profile check. The count grows by 5.
- [ ] **Step 2.** Run `apps.output.tests` and `apps.vod.tests` whole, each with and without
  `--keepdb`. Expected: OK, with the seed's 71 and 47 plus C-1, C-6 and D-4's additions plus 26
  and 34.
- [ ] **Step 3.** Commit in two calls, push, and open a draft PR.

#### PR description draft

> **test(output,vod): Hypothesis property tests for the EPG export, dummy-EPG, formatting, image-proxy and provider-ingest helpers (#92)**
>
> Five `SimpleTestCase` modules, 60 tests, about 12 s, under the shared derandomized profile.
>
> - `generate_custom_dummy_programs` is held to "any captured time or date yields a list of
>   programmes with start before end". It carries #90's and #211's names and C-1's edge cases as
>   `@example`s.
> - `extract_year` is held to "any JSON value yields an int or None". It carries #242's `1`, `2011`,
>   `[2011]`, `2011.5` and `True`, with C-6's expected values.
> - `is_proxyable_image_url` is pinned to exactly its three-prefix, case-sensitive allowlist, with
>   `file://`, `//`, `data:` and `javascript:` examples.
>
> Not asserted, filed separately:
> - `format_channel_number` raises on NaN or infinity, which a provider's `tvg-chno="inf"` can
>   probably reach.
> - `coerce_channel_profile_ids` raises on `1e999`.
> - `extract_duration_from_data` raises on a non-integer `duration_secs`.
>
> Each strategy is restricted, with a comment naming its finding.
>
> Break-checks: <paste>. Seams: <paste>. Closes #92, #210, #162 and #243. No existing test changed.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

### PR I-4: `fix/I-4-timeshift-property-tests`

- **Closes** #192, and duplicates #260, #142, #215, #55.
- **Depends on** D-3 **amended**.
- **Files** the five `apps/timeshift/tests/test_property_*.py` modules (Appendix D).
- **Labels** `apps.timeshift.tests`.
- **upstreamable** no. **Size** L.

#### Task 0: prerequisites

- [ ] **Step 1.** D-3 merged:
  `grep -c 'def _is_suffix_range' apps/timeshift/views.py` and
  `grep -c 'def is_near_eof_offset' apps/timeshift/stats.py` each print `1`.
- [ ] **Step 2.** D-3's non-ASCII digit guard: `grep -c 'def _ascii_digits' apps/timeshift/views.py`
  prints `1`, and prints `0` at seed. Read the helper. It must return
  `value.isascii() and value.isdigit()`, as plan D's Appendix C.2 at `b84cc664` has it. Then check
  that none of the three parsers calls a bare `isdigit()`. Run
  `grep -n 'isdigit()' apps/timeshift/views.py` and place each hit by function:
  - **Required:** at least one hit inside `_ascii_digits`. On D's final tree there are two: its
    return line and its docstring's `str.isdigit()`.
  - **Forbidden:** any hit inside `_parse_client_range`, `_is_suffix_range` or
    `_parse_content_range_header`.
  - **Allowed:** hits in any other function. That includes the one D-3 does not touch, in
    `_stream_stop_requested`: `:2499` at seed, and `:2525` after D-3 per plan D.

  If the required hit is missing or a forbidden one exists, STOP: the five superscript `@example`s
  will raise `ValueError`.

#### Task 1: extract and run

- [ ] **Step 1.** `git switch -c fix/I-4-timeshift-property-tests origin/main`.
- [ ] **Step 2.** Extract with prefix `apps/timeshift/tests/`. It must print five files, with 320,
  170, 345, 262 and 248 lines.
- [ ] **Step 3.** Run the five modules together, three times. Expected: `Ran 77 tests`, `OK`,
  identical each time, about 9 to 10 s of wall time.

#### Task 2: prove the seams (each edit is reverted)

| fix undone | edit | expected failure |
|---|---|---|
| D-3 #141 | in `_build_downstream_length_headers`, `if parsed_upstream:` back to `if upstream_content_range:` | `test_headers_never_carry_an_unsatisfiable_range_or_a_negative_length`: `-49 not >= 0` |
| D-3 #216 | `is_near_eof_offset` body back to `start >= max(0, total - EOF_PROBE_TAIL_BYTES)` | `test_an_archive_no_larger_than_the_window_has_no_tail` and the pool and stats #216 properties: `False is not true` and `'1700000000.0' != 1700000100.0` |
| D-3 #111 | drop the `if local_dt.second:` branch | `test_provider_zone_conversion_is_the_same_instant_and_keeps_requested_seconds`: `'2026-01-15:13-00' != '2026-01-15:13-00-45'` |
| D-3 non-ASCII digit guard | plan D's own break-check (Task 3.3 step 6 at `b84cc664`): change `_ascii_digits` to `return value.isdigit()` | `test_parse_client_range_is_none_or_a_satisfiable_pair_for_any_header`: `ValueError: invalid literal for int() with base 10: '²'` |

- [ ] **Step 1.** Run each row, paste the line, revert, and confirm
  `git diff --stat -- apps/timeshift` is empty.

#### Task 3: break-checks, one per module (each reverted)

| module | wrong edit | expected failure |
|---|---|---|
| timestamps | `client_duration_to_window` drops its `min(..., MAX_DURATION_MINUTES)` | `test_integer_hint_is_buffered_and_capped_or_rejected`: `481 != 480` |
| url_builders | format B's password becomes `quote(str(creds.password))`, the default `safe='/'` | `test_path_layout_is_exactly_six_segments_with_credentials_intact`: `7 != 6` |
| ranges | `_cap_open_ended_range` drops its `- 1` | `test_cap_applies_only_to_open_ended_ranges_and_caps_to_exactly_the_span`: `'bytes=0-1' != 'bytes=0-0'` |
| pool_decisions | the UA weight in `_score_pool_fingerprint` becomes 2 instead of 3 | `test_fingerprint_score_is_five_per_ip_match_plus_three_per_ua_match`: `2 != 3` |
| stats | `_client_paused` drops `"yes"` | `test_paused_is_one_true_or_yes_in_any_case_and_padding`: `False != True` |

- [ ] **Step 1.** Run each, paste the lines, revert, and confirm the diff is empty.

#### Task 4: the label, the profile check, and push

- [ ] **Step 1.** Profile check. The count grows by 5.
- [ ] **Step 2.** `redis-cli flushall`, then run `apps.timeshift.tests` whole, with and without
  `--keepdb`. Expected: OK, with plan D's measured 362 after D-3 plus 77 = 439, plus any G
  additions. `CLAUDE.md` § Testing warns that this label's outcome depends on Redis state, which is
  why the flush comes first.
- [ ] **Step 3.** Commit in two calls, push, and open a draft PR.

#### PR description draft

> **test(timeshift): Hypothesis property tests for catch-up timestamps, URL builders, Range handling, pool decisions and playback stats (#192)**
>
> Five `SimpleTestCase` modules, 77 tests, about 9 s, under the shared derandomized profile.
>
> They are written against D-3's contracts:
> - a suffix range and an inverted range are not parsed as prefixes;
> - no downstream `Content-Range` is unsatisfiable, and no `Content-Length` is negative;
> - an archive of 2 MiB or less has no EOF-probe tail;
> - a non-UTC provider zone keeps the requested seconds.
>
> The counterexamples are `@example`s: #141's five, #216's 1.5 MiB archive and #111's Brussels start.
> So are the Latin-1 superscript digits (`bytes=²-`) that a bare `isdigit()` guard lets through to
> `int()`. D-3 was amended for those before it merged.
>
> Stats strategies draw real epoch anchors, per #54's invalid ruling.
>
> Not asserted, filed separately: `normalize_catchup_timestamp_input` raises on `111111111²` and on
> ISO timestamps at the calendar edge. Until that is fixed, instants are drawn from 1900 to 2100,
> and the arbitrary-text strategy excludes both input shapes.
>
> Break-checks: <paste>. Seams: <paste>. Closes #192, #260, #142, #215 and #55. No existing test
> changed.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Timings

Measured in the `fixplan-I` container, three runs each, with identical results on every run. The
figures are for the modules on the fixed tree, not the whole label.

| PR | modules | tests | wall per run |
|---|---|---|---|
| I-1 epg | 6 | 53 | 7.9 to 8.3 s |
| I-2 m3u | 8 | 49 | 6.7 to 8.3 s |
| I-3 output | 3 | 26 | about 6 s (1.3 + 3.8 + 1.0) |
| I-3 vod | 2 | 34 | 7 to 8 s (2.5 to 2.9 + 4.0 to 4.3) |
| I-4 timeshift | 5 | 77 | 9.2 to 9.6 s |

For comparison, the whole labels at seed (`--keepdb`, Redis flushed) took these internal run times:

| label | tests | run time |
|---|---|---|
| `apps.epg.tests` | 295 | 12.4 s |
| `apps.timeshift.tests` | 349 | 0.5 s |
| `apps.m3u.tests` | 164 | 7.3 s |
| `apps.output.tests` | 71 | 0.6 s |
| `apps.vod.tests` | 47 | 0.6 s |

The timeshift, output and vod labels grow proportionally the most. Each still runs in its own CI
container, so the added cost is under 10 s per job.

---

## Findings for the lead to file

Found while prototyping, reproduced at seed, and **kept out of every module**, per brief rule 6 and
Global constraint 5. None has an issue: each was searched with
`gh issue list --repo D10Scot/Dispatcharr --state all --search '<function>'`. Each is a candidate issue
for whichever category owns crashes or correctness. The property that would pin it is named, so the
fix PR widens that strategy and adds the `@example`.

| # | severity | defect | seed `file:line` | shrunk input | property to widen |
|---|---|---|---|---|---|
| F-1 | medium | `parse_text_query` raises `IndexError` when a letter whose `.upper()` is longer (`ß`, `ŉ`, `ﬃ`) sits before an operator word. Operator positions come from `remaining.upper()` but slice `remaining`. It 500s EPG search (`apps/epg/api_views.py:262`, `:268`), DVR series rules (`apps/channels/tasks.py:591`, `:598`) and recordings search (`apps/channels/api_views.py:4219`, `:4225`). A German `Straße AND Krimi` is enough. | `apps/epg/query_utils.py:103-127` | `parse_text_query("title", "ß a AND b")` | I-1 `test_any_length_preserving_text_builds_a_q_without_raising`: drop the filter and add `@example("ß a AND b")`. **Removing the filter alone does not redden in 200 draws**, so the `@example` is required. |
| F-2 | low | One `<programme` start tag over 4096 bytes with no `>` drops every later programme in that 8 MiB read from the index. `build_programme_index` `break`s and discards the unscanned middle. Measured with the DB stubbed: 36 of 200 channels indexed, against 200 in the control. | `apps/epg/tasks.py:2929-2934`, `:3027-3031` | a 5000-byte unterminated tag | I-1 programme_index oracle property (buffers under `_MAX_START_TAG`) |
| F-3 | low | `xmltv_ns` totals (`s/total . e/total`, allowed by the XMLTV DTD) are silently dropped because `int("0/3")` fails. A negative part stores season 0 or lower. | `apps/epg/tasks.py:2568-2582` | `"0/3 . 1/10 ."` | I-1 `test_xmltv_ns_is_zero_based_and_stored_one_based` |
| F-4 | **medium** | A second stream on one pooled profile leaks a shared credential slot. One release key is stored per profile (`_remember_credential_release_key`), and the first release deletes it, so the second release decrements nothing. With `max_streams=2`, two reserves then two releases leave the credential counter at 1. The key has no TTL, so the counter ratchets toward a permanent `credential_full`. Channels, timeshift and VOD all reserve against multi-stream profiles. Reproduced with the module's fake Redis and verified by reading. | `apps/m3u/connection_pool.py:241-244`, `:247-258` | reserve, reserve, release, release on `max_streams=2` | I-2 `test_counters_track_the_streams_held_one_stream_per_profile`: allow N streams per profile |
| F-5 | low | `normalize_catchup_timestamp_input` raises instead of returning `None`. `isdigit()` then `int()` fails on `'111111111²'` (`:70`). The ISO branch catches only `ValueError`, so `OverflowError` escapes at the calendar edges (`:80-87`). `convert_timestamp_to_provider_tz` raises `OverflowError` for `'9999-12-31:23-59'` in Asia/Tokyo (`:159`). `_serve_catchup` (`apps/timeshift/views.py:341`) and the native API (`apps/timeshift/api_views.py:127`) answer 500 where 400 belongs, for an authenticated catch-up user. A three-line fix was prototyped and verified: `isascii()`, `except (ValueError, OverflowError)`, and a `try` around `astimezone`. | `apps/timeshift/helpers.py:70`, `:80-87`, `:159` | `'111111111²'`, `'0001-01-01T00:00+01:00'` | I-4 `timestamp_text`: drop the category-No and edge-year exclusions and the 1900 to 2100 window, then add `'111111111²'`, `'0001-01-01T00:00+01:00'` and `'9999-12-31T23:59-01:00'` as `@example`s on `test_normalize_returns_iso_shape_or_none_for_arbitrary_text` |
| F-6 | low | `extract_duration_from_data` calls `int(duration_secs)` outside any `try` (`:1171`), so `"1.5"`, `"abc"`, a list, inf and nan raise. `isdigit()` then `int()` (`:1175-1176`) raises on `"²"`. The per-movie `try` drops one movie per bad row, the impact C-6 records for #242. | `apps/vod/tasks.py:1171`, `:1175-1176` | `{"duration_secs": "1.5"}`, `{"duration": "²"}` | I-3 `test_extract_duration_never_raises_on_integer_seconds_or_duration_text` |
| F-7 | low (traced, not run end to end) | `format_channel_number` raises on NaN or infinity (`:53`, `value == int(value)`). `float()` accepts `tvg-chno="inf"` (`apps/m3u/tasks.py:1381`, `:1165`). Provider-mode auto-sync uses it verbatim (`apps/m3u/tasks.py:1948-1950`, `apps/channels/tasks.py:3503`). The M3U, XMLTV and HDHR lineup format it unguarded (`apps/output/views.py:271`, `apps/output/epg.py:1242`, `apps/hdhr/api_views.py:166`). #162 judged it unreachable; the trace says otherwise. The fix belongs at the parse sites (`math.isfinite`). | `apps/channels/utils.py:53` | `float("inf")` | I-3 finite-float properties in output_formatting |
| F-8 | low | `coerce_channel_profile_ids` raises `OverflowError` on a profile id of `1e999`: `json.loads` yields `inf`, and `(TypeError, ValueError)` misses it. Callers are admin-only (`apps/m3u/api_views.py:523`, `apps/channels/serializers.py:222`). | `apps/channels/utils.py:40-42` | `[1e999]` | I-3 `test_any_json_value_returns_a_dict_with_int_ids` |
| F-9 | minor | `normalize_server_url` drops `;params` from the last path segment, so `http://h/a;b` becomes `http://h/a`, and `';/'` takes two passes to settle. | `core/xtream_codes.py:25` | `'http://h/a;b'` | I-2 `test_normalising_twice_changes_nothing` |

Also noted, and not candidate issues:
- `parse_text_query`'s regex mode still splits on parentheses and `AND`/`OR`, against its docstring
  (`apps/epg/query_utils.py:42`). Either the docstring or the code is wrong.
- `_sd_image_width` raises `OverflowError` on a JSON `Infinity` width (`apps/epg/sd_tasks.py:140-143`),
  but Schedules Direct is not a hostile source.
- An admin-set `program_duration=0` would make the dummy-EPG fill loops spin forever
  (`apps/output/epg.py`, the `current_time += timedelta(minutes=program_duration)` loops). It is
  admin-configured, not provider input.
- `tests/test_redaction.py:27-28` cites the deleted
  `apps/proxy/live_proxy/tests/test_property_ts_realignment.py` for its profile rationale. Every new
  module states the rationale inline instead. Fixing that comment would edit an existing test module
  for no behaviour change, so it is left to whoever next edits the file.

---

## Coverage table

| issue | disposition | PR section |
|---|---|---|
| 202 | survivor (epg) | I-1 |
| 274 | duplicate of #202 | I-1 |
| 158 | duplicate of #202 | I-1 |
| 74 | duplicate of #202 | I-1 |
| 192 | survivor (timeshift) | I-4 |
| 260 | duplicate of #192 | I-4 |
| 142 | duplicate of #192 | I-4 |
| 215 | duplicate of #192 | I-4 |
| 55 | duplicate of #192 | I-4 |
| 218 | survivor (m3u) | I-2 |
| 145 | duplicate of #218 | I-2 |
| 200 | duplicate of #218 (the overflow filter is removed once C-3 fixes #199) | I-2 |
| 69 | duplicate of #218 | I-2 |
| 92 | survivor (output + vod) | I-3 |
| 210 | duplicate of #92 | I-3 |
| 162 | duplicate of #92 | I-3 |
| 243 | duplicate of #92 (the `extract_year` strategy is widened once C-6 fixes #242) | I-3 |
| 109 | parked by user 2026-09-23; no memo, no plan | — |

---

## Open questions for the user

1. **F-5, timeshift timestamp crashes: file separately, or fold into I-4?** The default is to **file
   it separately**, owned by whichever category takes crashes. I-4 stays test-only, and its timestamp
   properties draw years 1900 to 2100 with a comment. The alternative is to fold the three-line fix,
   already prototyped and verified, into I-4. That removes the restriction now, but makes I-4 a fix
   PR with a production diff and one more reviewer axis. The code shape differs, which is why this is
   asked rather than decided.

The two sibling-plan amendments (C-1's year bound, D-3's ASCII guard) are not questions for the user.
They were reported to the lead on 2026-09-23, and Task 0 of I-3 and I-4 STOPs until they land.

---

## Appendices: the modules, verbatim

Every module below ran in the `fixplan-I` container at seed `a54b09a9`. The C- or D-fix it depends
on was applied by hand, and the module was then reverted out of the tree. Each module passed three
identical runs and its break-checks. They are the deliverable (Global constraint 5), so extract them
with the script in § Appendix extraction.

**The appendix text itself was re-run, not only the scratch copies it was spliced from.** All 24
modules were extracted from this document with § Appendix extraction's regex into the worktree and
run at seed. Every domain reproduced the seed column of § Prerequisites exactly:

| domain | tests | seed result |
|---|---|---|
| epg | 52 | 1 FAIL (#75), 1 import ERROR (C-2's helper) |
| m3u | 49 | 10 red |
| output | 26 | 2 ERROR |
| vod | 34 | 7 ERROR |
| timeshift | 77 | 15 red |

Three domains were also taken to green from the extracted text:

| domain | fix applied | result |
|---|---|---|
| m3u | the C-3, C-4 (adopted rule) and C-5 hunks | 49 OK, 3 of 3 runs |
| timeshift | D Appendix C plus the ASCII guard | 77 OK |
| vod | C-6's one-line `str()` coercion | 34 OK |

The tree was then reverted. The epg and output green runs, with C-2 Appendix A and the amended C-1
applied by hand, were measured on the prototypes before splicing, not on the extracted text. The
extracted text is byte-identical to those prototypes: the round trip is checked with `cmp`. Each
PR's Task 1 Step 3 is the run on the extracted text against the merged fix, so I-1 and I-3 get that
run at implementation time.

**Round 1 fixes, re-run after editing (2026-09-23).** Editing a test's source re-seeds its
derandomized draws, so each edited module was re-run three times.

- **Modules edited.** Six changed comments and docstrings only: the finding labels now match
  § Findings (F-1, F-3, F-4, F-6, F-7, F-8, F-9). One, timestamps, changed its strategy (F-5, below).
- **Re-run on the C fixes (C-6 for vod), three runs.** The eight m3u modules, vod provider_helpers,
  output formatting and the two edited epg modules: 113 of 113 OK in all three runs.
- **Timestamps.** 77 of 77 OK in three runs on D's final Appendix C. At seed its only failure is still
  the #111 test.
- **F-5 shapes.** Probed on D's final tree, all three still raise: `'111111111²'` raises
  `ValueError`, and `'0001-01-01T00:00+01:00'` and `'9999-12-31T23:59-01:00'` raise `OverflowError`.
  So the exclusions guard a live defect, not a fixed one.
- **The category-No exclusion closes the whole class.** Every character that is `isdigit()` but not
  decimal is in Unicode category No. That is 128 code points on Python 3.13.15, checked
  exhaustively, and the same count on the host.


### Appendix A: PR I-1, epg

#### `apps/epg/tests/test_property_xmltv_time.py`

<!-- file: apps/epg/tests/test_property_xmltv_time.py -->
```python
"""Property-based tests for ``parse_xmltv_time`` (apps/epg/tasks.py:2504).

Every ``<programme start= stop=>`` of every provider file goes through this
parser. Its contract, read from the seed code:

* ``YYYYMMDDHHMMSS`` alone is a UTC wall clock (``make_aware(..., utc)``).
* ``YYYYMMDDHHMMSS ±HHMM`` is local time at that offset, returned in UTC.
* Anything else raises ``ValueError`` and nothing else: the ``except`` block
  logs and re-raises, and both bulk parsers (``:1730``, ``:2222``) catch per
  programme. C-2 (#76, #156) makes the two byte-offset helpers catch it too
  and deliberately keeps this raising contract, so it is pinned here.
* C-2 (#75): the adjacent form ``YYYYMMDDHHMMSS±HHMM`` is the same instant as
  the spaced form. At seed the adjacent offset is silently read as UTC.

Closes the parse_xmltv_time part of #202 (and duplicates #274, #158, #74).
"""

import logging
import string
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.epg import tasks as epg_tasks
from apps.epg.tasks import parse_xmltv_time

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


# Wall-clock fields. Day <= 28 keeps every month valid; the base range keeps
# a +/-23:59 shift inside datetime's year range.
wall_clocks = st.builds(
    datetime,
    year=st.integers(1971, 2100),
    month=st.integers(1, 12),
    day=st.integers(1, 28),
    hour=st.integers(0, 23),
    minute=st.integers(0, 59),
    second=st.integers(0, 59),
)
# dt_timezone accepts |offset| < 24h, so every HH in 00..23 and MM in 00..59
# is a valid offset. HH=24 is the #76 counterexample and must raise.
offsets = st.tuples(
    st.sampled_from("+-"), st.integers(0, 23), st.integers(0, 59)
)

# Corrupt-provider text, biased towards the timestamp alphabet so that most
# draws get past the 14-character strptime and into the offset branch.
junk = st.one_of(
    st.text(max_size=40),
    st.text(alphabet=string.digits + "+- :ZT.", max_size=30),
    st.builds(
        lambda base, tail: base + tail,
        st.text(alphabet=string.digits, min_size=14, max_size=14),
        st.text(alphabet=string.digits + "+- ", max_size=8),
    ),
)


def _stamp(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def _expected_utc(dt, sign, hh, mm):
    """Oracle: local wall clock at +/-HH:MM, as a UTC instant, by arithmetic."""
    delta = timedelta(hours=hh, minutes=mm)
    naive_utc = dt - delta if sign == "+" else dt + delta
    return naive_utc.replace(tzinfo=dt_timezone.utc)


class _QuietParserLog(SimpleTestCase):
    """parse_xmltv_time logs every failure at ERROR with a traceback; silence
    it for the test so 200 malformed draws do not flood the CI log."""

    def setUp(self):
        for level in ("error", "warning"):
            patcher = mock.patch.object(epg_tasks.logger, level)
            patcher.start()
            self.addCleanup(patcher.stop)


class ParseXmltvTimeProperties(_QuietParserLog):
    @given(dt=wall_clocks)
    def test_a_bare_timestamp_is_the_same_wall_clock_in_utc(self, dt):
        result = parse_xmltv_time(_stamp(dt))
        self.assertEqual(result, dt.replace(tzinfo=dt_timezone.utc))
        self.assertEqual(result.utcoffset(), timedelta(0))

    @given(dt=wall_clocks, offset=offsets)
    def test_a_spaced_offset_is_local_time_at_that_offset_returned_in_utc(
        self, dt, offset
    ):
        sign, hh, mm = offset
        result = parse_xmltv_time(f"{_stamp(dt)} {sign}{hh:02d}{mm:02d}")
        self.assertEqual(result, _expected_utc(dt, sign, hh, mm))
        self.assertEqual(result.utcoffset(), timedelta(0))

    @example(dt=datetime(2026, 7, 28, 18, 30, 0), offset=("+", 5, 30))  # #75
    @example(dt=datetime(2026, 7, 28, 18, 30, 0), offset=("-", 8, 0))  # #75
    @given(dt=wall_clocks, offset=offsets)
    def test_an_adjacent_offset_is_the_same_instant_as_the_spaced_form(
        self, dt, offset
    ):
        sign, hh, mm = offset
        spaced = parse_xmltv_time(f"{_stamp(dt)} {sign}{hh:02d}{mm:02d}")
        adjacent = parse_xmltv_time(f"{_stamp(dt)}{sign}{hh:02d}{mm:02d}")
        self.assertEqual(adjacent, spaced)

    @example(junk="20260728183000 +2400")  # #76: out-of-range offset hour
    @example(junk="20260728183000 +2460")  # #156: out-of-range offset minute
    @example(junk="20260728183000+2400")  # #75 x #76: adjacent and out of range
    @given(junk=junk)
    def test_arbitrary_text_raises_only_value_error_or_parses_to_aware_utc(
        self, junk
    ):
        try:
            result = parse_xmltv_time(junk)
        except ValueError:
            return  # the documented contract every caller catches
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.utcoffset(), timedelta(0))

    def test_out_of_range_offsets_keep_raising_value_error(self):
        # C-2 fixes #76 in the callers, not here: the raise is the contract.
        for stamp in ("20260728183000 +2400", "20260728183000 +2460"):
            with self.subTest(stamp=stamp):
                with self.assertRaises(ValueError):
                    parse_xmltv_time(stamp)
```

#### `apps/epg/tests/test_property_programme_index.py`

<!-- file: apps/epg/tests/test_property_programme_index.py -->
```python
"""Property-based tests for the byte-offset programme index's building blocks.

``build_programme_index`` (apps/epg/tasks.py:2953) and the two current-programme
helpers scan raw XMLTV bytes rather than parsing XML, so every building block
consumes provider-controlled bytes:

* ``_PrependStream`` (:249) - ``_open_xmltv_file`` streams the HTML-entity
  DOCTYPE in front of the file; lxml may ``read()`` with any size.
* ``_open_xmltv_file`` (:290) - injects that DOCTYPE once, after an XML
  declaration if present, and never into a file that declares its own.
* ``_find_programme_tag`` (:2910) - the scanner. Finds the first
  ``<programme`` followed by whitespace, ``>`` or ``/``.
* ``_CHANNEL_ATTR_RE`` (:2894) - the ``channel=`` extractor.
* ``_decode_channel_id`` is covered by test_property_channel_id_parity.py,
  which needs C-2's new signature.

Closes the programme-index part of #202 (and duplicates #274, #158, #74).
"""

import io
import os
import re
import string
import tempfile
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg import tasks as epg_tasks
from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _HTML_ENTITY_DOCTYPE,
    _MAX_START_TAG,
    _PROGRAMME_TAG,
    _PrependStream,
    _find_programme_tag,
    _open_xmltv_file,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class _QuietTaskWarnings(SimpleTestCase):
    """Silence apps.epg.tasks' per-call WARNING so 200 draws do not flood the CI log."""

    def setUp(self):
        patcher = mock.patch.object(epg_tasks.logger, "warning")
        patcher.start()
        self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# _PrependStream
# ---------------------------------------------------------------------------

class PrependStreamProperties(SimpleTestCase):
    @given(
        prefix=st.binary(max_size=64),
        body=st.binary(max_size=256),
        sizes=st.lists(st.integers(0, 80), max_size=30),
    )
    def test_any_sequence_of_sized_reads_reassembles_prefix_then_body(
        self, prefix, body, sizes
    ):
        stream = _PrependStream(prefix, io.BytesIO(body))
        out = bytearray()
        for size in sizes:
            chunk = stream.read(size)
            self.assertLessEqual(len(chunk), size)  # read(n) never over-returns
            out += chunk
        out += stream.read()  # drain
        self.assertEqual(bytes(out), prefix + body)
        self.assertEqual(stream.read(), b"")  # exhausted is empty, not an error
        self.assertEqual(stream.read(7), b"")


# ---------------------------------------------------------------------------
# _open_xmltv_file
# ---------------------------------------------------------------------------

_XML_DECL = b'<?xml version="1.0" encoding="UTF-8"?>'
# Readable text; '&' and '<' are only ever emitted as the entity refs below.
_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + " .,-", max_size=40
)


def _write_tmp(test, data):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    test.addCleanup(os.unlink, path)
    return path


def _read_all(stream):
    try:
        return stream.read()
    finally:
        stream.close()


class OpenXmltvFileProperties(SimpleTestCase):
    @given(with_decl=st.booleans(), title=_TEXT, padding=st.integers(0, 600))
    def test_the_doctype_is_injected_once_and_the_file_bytes_survive(
        self, with_decl, title, padding
    ):
        body = (
            b"<tv>" + b" " * padding
            + b"<programme><title>" + title.encode() + b"&eacute;</title>"
            + b"</programme></tv>"
        )
        original = (_XML_DECL + b"\n" if with_decl else b"") + body
        out = _read_all(_open_xmltv_file(_write_tmp(self, original)))
        self.assertEqual(out.count(_HTML_ENTITY_DOCTYPE), 1)
        if with_decl:
            # Injected right after the declaration, which stays first.
            self.assertTrue(out.startswith(_XML_DECL + b"\n" + _HTML_ENTITY_DOCTYPE))
            self.assertEqual(
                out.replace(b"\n" + _HTML_ENTITY_DOCTYPE, b"", 1), original
            )
        else:
            self.assertEqual(out, _HTML_ENTITY_DOCTYPE + original)
        # The point of the injection: lxml resolves an HTML 4 entity.
        root = etree.fromstring(out)
        self.assertEqual(root.findtext("programme/title"), title + "é")

    @given(
        doctype=st.sampled_from(
            [b"<!DOCTYPE tv SYSTEM \"xmltv.dtd\">", b"<!doctype tv>", b"<!DocType tv>"]
        ),
        title=_TEXT,
    )
    def test_a_file_that_declares_its_own_doctype_is_returned_unchanged(
        self, doctype, title
    ):
        original = (
            _XML_DECL + b"\n" + doctype + b"\n<tv><programme><title>"
            + title.encode() + b"</title></programme></tv>"
        )
        out = _read_all(_open_xmltv_file(_write_tmp(self, original)))
        self.assertEqual(out, original)


# ---------------------------------------------------------------------------
# _find_programme_tag
# ---------------------------------------------------------------------------

# Byte soup biased towards the needle and its false-match neighbours.
_FRAGMENTS = st.sampled_from(
    [b"<programme", b"<programme ", b"<programme>", b"<programme/",
     b"<programmeX", b"<programmes", b"<program", b">", b" ", b"\t",
     b'channel="a"', b"x", b"<", b"</programme>"]
)
tag_soup = st.one_of(
    st.binary(max_size=200),
    st.lists(_FRAGMENTS, max_size=25).map(b"".join),
)
_FIRST_CANDIDATE = re.compile(rb"<programme(?:[ \t\n\r>/]|\Z)")


class FindProgrammeTagProperties(_QuietTaskWarnings):
    @given(buf=tag_soup, start=st.integers(0, 220))
    def test_finds_the_first_real_start_tag_and_its_closing_bracket(
        self, buf, start
    ):
        # Buffers stay far below _MAX_START_TAG, so the oversize arm cannot
        # fire here; it has its own test below.
        pos, end = _find_programme_tag(buf, start)
        # Oracle: a regex for "<programme" followed by a tag-follow byte, or
        # at the very end of the buffer (the "need more data" case).
        m = _FIRST_CANDIDATE.search(buf, start)
        if m is None:
            self.assertEqual((pos, end), (-1, -1))
            return
        self.assertEqual(pos, m.start())
        close = buf.find(b">", pos + len(_PROGRAMME_TAG))
        self.assertEqual(end, close)  # -1 means "need more data"

    @given(prefix=st.binary(max_size=40).filter(lambda b: _PROGRAMME_TAG not in b))
    def test_a_false_match_is_skipped_and_the_next_real_tag_found(self, prefix):
        buf = prefix + b"<programmeXYZ a='1'> <programme channel='b'>"
        pos, end = _find_programme_tag(buf, 0)
        self.assertEqual(pos, buf.rfind(b"<programme "))
        self.assertEqual(end, len(buf) - 1)

    @given(extra=st.integers(0, 64))
    def test_a_start_tag_longer_than_the_bound_is_rejected_not_waited_on(
        self, extra
    ):
        buf = b"<programme " + b"a" * (_MAX_START_TAG + extra)
        self.assertEqual(_find_programme_tag(buf, 0), (-1, -1))

    @given(short=st.integers(0, _MAX_START_TAG - len(b"<programme ") - 1))
    def test_an_unterminated_tag_within_the_bound_asks_for_more_data(self, short):
        buf = b"<programme " + b"a" * short
        self.assertEqual(_find_programme_tag(buf, 0), (0, -1))


# ---------------------------------------------------------------------------
# _CHANNEL_ATTR_RE
# ---------------------------------------------------------------------------

class ChannelAttrRegexProperties(SimpleTestCase):
    @given(buf=st.binary(max_size=200) | tag_soup)
    def test_exactly_one_quote_style_captures_and_never_contains_its_quote(
        self, buf
    ):
        for m in _CHANNEL_ATTR_RE.finditer(buf):
            dq, sq = m.group(1), m.group(2)
            self.assertEqual((dq is not None) + (sq is not None), 1)
            if dq is not None:
                self.assertTrue(dq)
                self.assertNotIn(b'"', dq)
            else:
                self.assertTrue(sq)
                self.assertNotIn(b"'", sq)

    @given(
        value=st.text(
            alphabet=string.ascii_letters + string.digits + " \t-_.:/&;#'",
            min_size=1, max_size=40,
        ),
        spaces=st.sampled_from(["", " ", "  ", "\t"]),
    )
    def test_a_double_quoted_value_round_trips_verbatim(self, value, spaces):
        buf = f'<programme start="x" channel{spaces}={spaces}"{value}">'.encode()
        m = _CHANNEL_ATTR_RE.search(buf)
        self.assertEqual(m.group(1), value.encode())

    def test_an_empty_channel_attribute_never_matches(self):
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b'<programme channel="">'))
        self.assertIsNone(_CHANNEL_ATTR_RE.search(b"<programme channel=''>"))
```

#### `apps/epg/tests/test_property_channel_id_parity.py`

<!-- file: apps/epg/tests/test_property_channel_id_parity.py -->
```python
"""Property: the programme index's channel key equals the value lxml stores (#157).

``build_programme_index`` (apps/epg/tasks.py:2953) keys its byte-offset index
with ``_CHANNEL_ATTR_RE`` (:2894) plus ``_decode_channel_id`` (:2902), while
``parse_programs_for_source`` stores lxml's recover-mode value
(:2204-2214) behind ``_open_xmltv_file`` (:290). ``find_current_program_for_tvg_id``
joins the two, so any disagreement makes that channel's current programme
invisible. At seed they disagree for HTML5-only entities, for HTML 4 entities in
a file carrying its own DOCTYPE, for literal tabs/newlines and for
semicolon-less entities. C-2 (#157) changes the signature to
``_decode_channel_id(raw, quote=b'"', entity_doctype=True)`` and adds
``_xmltv_file_gets_entity_doctype(file_path)``; this module is written against
that and therefore lands after C-2.

The oracle is lxml's own parse of a real file through ``_open_xmltv_file``,
which the byte-level path never calls, so the property is not tautological.

Closes the _decode_channel_id cross-validation part of #202 (and duplicates
#274, #158, #74).
"""

import os
import tempfile

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg.tasks import (
    _CHANNEL_ATTR_RE,
    _decode_channel_id,
    _open_xmltv_file,
    _xmltv_file_gets_entity_doctype,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_XML_DECL = b'<?xml version="1.0" encoding="UTF-8"?>'


def _write_tmp(test, data):
    fd, path = tempfile.mkstemp(suffix=".xml")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    test.addCleanup(os.unlink, path)
    return path


# Byte soup for the no-raise property (same shape as the index scanner's).
_FRAGMENTS = st.sampled_from(
    [b"<programme ", b'channel="', b"channel='", b'"', b"'", b"&", b";",
     b"&amp;", b"&eacute", b"&#", b"x", b" ", b"\t", b"\xff", b"\xc3"]
)
tag_soup = st.lists(_FRAGMENTS, max_size=25).map(b"".join)

# Pieces of a provider channel id: plain text, whitespace escapes lxml
# normalises, HTML 4 and HTML5-only named entities, numeric refs, and
# malformed refs (no semicolon, unknown name, bare ampersand).
_ID_PIECES = st.sampled_from(
    ["a", "B", "7", ".", "-", "_", " ", "\t", "\n", "\r", "é", "日",
     "&amp;", "&lt;", "&gt;", "&apos;", "&quot;", "&eacute;", "&nbsp;",
     "&Uuml;", "&NewLine;", "&Tab;", "&#233;", "&#x41;", "&#9;", "&eacute",
     "&bogus;", "&"]
)
channel_ids = st.lists(_ID_PIECES, min_size=1, max_size=8).map("".join)

_OWN_DOCTYPE = b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'


def _lxml_programme_channel(path):
    """Oracle: the channel value the bulk parser stores, through the same
    _open_xmltv_file + recover-mode iterparse (tasks.py:2204-2214), stripped
    as EPGData.tvg_id is. None if lxml recovered no <programme>."""
    source = _open_xmltv_file(path)
    try:
        for _, elem in etree.iterparse(
            source, events=("end",), tag="programme",
            remove_blank_text=True, recover=True,
        ):
            value = elem.get("channel")
            return None if value is None else value.strip()
    finally:
        source.close()
    return None


class DecodeChannelIdMatchesLxmlProperties(SimpleTestCase):
    # C-2's #157 table, every divergent row plus the two the existing tests pin.
    @example(raw="a&NewLine;b", quote='"', own_doctype=False)  # #157 HTML5-only name
    @example(raw="a&eacute;b", quote='"', own_doctype=True)  # #157 own DOCTYPE
    @example(raw="a\tb", quote='"', own_doctype=False)  # #157 literal tab
    @example(raw="a&eacuteb", quote='"', own_doctype=False)  # #157 no semicolon
    @example(raw="a&eacute;b", quote='"', own_doctype=False)  # #157 control
    @example(raw="a&#233;b", quote='"', own_doctype=False)  # #157 control
    @example(raw=" A&amp;E.us ", quote='"', own_doctype=False)  # test_programme_index.py:170
    @example(raw="it&apos;s", quote="'", own_doctype=False)  # test_programme_index.py:406
    @given(
        raw=channel_ids,
        quote=st.sampled_from(['"', "'"]),
        own_doctype=st.booleans(),
    )
    def test_the_index_key_equals_the_value_lxml_stores(
        self, raw, quote, own_doctype
    ):
        raw = raw.replace(quote, "")
        if not raw:
            raw = "a"
        doc = (
            _XML_DECL + b"\n" + (_OWN_DOCTYPE if own_doctype else b"")
            + b"<tv><programme start=\"20260101000000 +0000\" channel="
            + quote.encode() + raw.encode() + quote.encode()
            + b"><title>t</title></programme></tv>"
        )
        path = _write_tmp(self, doc)
        stored = _lxml_programme_channel(path)
        if stored is None:
            return  # lxml dropped the programme: no row, nothing to join
        # The byte-level path, exactly as build_programme_index takes it.
        m = _CHANNEL_ATTR_RE.search(doc)
        group_quote = b'"' if m.group(1) is not None else b"'"
        key = _decode_channel_id(
            m.group(1) or m.group(2), group_quote,
            _xmltv_file_gets_entity_doctype(path),
        )
        self.assertEqual(key, stored)

    @given(buf=st.binary(max_size=200) | tag_soup, entity_doctype=st.booleans())
    def test_every_captured_id_decodes_to_a_stripped_string_without_raising(
        self, buf, entity_doctype
    ):
        for m in _CHANNEL_ATTR_RE.finditer(buf):
            quote = b'"' if m.group(1) is not None else b"'"
            key = _decode_channel_id(m.group(1) or m.group(2), quote, entity_doctype)
            self.assertIsInstance(key, str)
            self.assertEqual(key, key.strip())
```

#### `apps/epg/tests/test_property_programme_metadata.py`

<!-- file: apps/epg/tests/test_property_programme_metadata.py -->
```python
"""Property-based tests for per-programme metadata extraction and file sniffing.

Surfaces (seed a54b09a9), all fed by provider XMLTV:

* ``extract_season_episode_from_description`` (apps/epg/utils.py:58) and
  ``extract_season_episode`` (:76) - the description/onscreen fallbacks.
* ``extract_custom_properties`` (apps/epg/tasks.py:2547) - runs on every
  programme of every refresh.
* ``_programme_to_dict`` (:2939) - the current-programme API's serializer.
* ``_parse_programme_element`` (:242) - the parser behind the offset lookups;
  both callers (``:3197``, ``:3291``) catch exactly ``etree.XMLSyntaxError``.
* ``detect_file_format`` (:2787) - magic bytes first, then the extension.
* ``validate_icon_url_fast`` (:325) - the icon-URL length guard.

Closes the metadata part of #202 (and duplicates #274, #158, #74).
"""

import html
import mimetypes
import re
import string
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st
from lxml import etree

from apps.epg import tasks as epg_tasks
from apps.epg.models import EPGData
from apps.epg.tasks import (
    _parse_programme_element,
    _programme_to_dict,
    detect_file_format,
    extract_custom_properties,
    validate_icon_url_fast,
)
from apps.epg.utils import (
    extract_season_episode,
    extract_season_episode_from_description,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class _QuietTaskWarnings(SimpleTestCase):
    """Silence apps.epg.tasks' per-call WARNING so 200 draws do not flood the CI log."""

    def setUp(self):
        patcher = mock.patch.object(epg_tasks.logger, "warning")
        patcher.start()
        self.addCleanup(patcher.stop)

# Text sizes stay far below Python's 4300-digit int() limit on purpose: a
# longer digit run raises ValueError from the unguarded int() calls, which is
# not a realistic provider value.
_SEP = st.sampled_from(["", " ", "-", ": ", " - ", ".", "  "])
# A rest that starts with a digit would extend the greedy episode number.
_REST = st.text(max_size=60).filter(lambda r: not re.match(r"\d", r))


# ---------------------------------------------------------------------------
# Season/episode from description
# ---------------------------------------------------------------------------

class SeasonEpisodeFromDescriptionProperties(SimpleTestCase):
    @given(desc=st.one_of(st.none(), st.text(max_size=120)))
    def test_a_description_is_either_untouched_or_cut_to_a_stripped_suffix(
        self, desc
    ):
        season, episode, cleaned = extract_season_episode_from_description(desc)
        if season is None:
            self.assertIsNone(episode)
            self.assertIs(cleaned, desc)  # returned unchanged, same object
            return
        self.assertIsInstance(season, int)
        self.assertIsInstance(episode, int)
        # It can only cut a recognised prefix, never invent text.
        self.assertTrue(desc.rstrip().endswith(cleaned))
        self.assertEqual(cleaned, cleaned.strip())

    @given(
        form=st.sampled_from(["S{s}E{e}", "s{s} e{e}", "Season {s} Episode {e}",
                              "season{s}episode{e}", "{s}x{e:02d}"]),
        season=st.integers(0, 999),
        episode=st.integers(10, 9999),
        lead=st.sampled_from(["", " ", "- ", ": "]),
        sep=_SEP,
        rest=_REST,
    )
    def test_every_documented_prefix_form_round_trips(
        self, form, season, episode, lead, sep, rest
    ):
        desc = lead + form.format(s=season, e=episode) + sep + rest
        s, e, _ = extract_season_episode_from_description(desc)
        self.assertEqual((s, e), (season, episode))

    @given(season=st.integers(0, 99), episode=st.integers(0, 9), rest=_REST)
    def test_a_single_digit_nx_episode_is_not_recognised(self, season, episode, rest):
        # The 1x01 form requires a 2+ digit episode (utils.py:28-29) so that
        # text like "4x4 rally" is not read as season 4 episode 4.
        s, e, cleaned = extract_season_episode_from_description(
            f"{season}x{episode} {rest}".replace("S", "").replace("s", "")
        )
        self.assertEqual((s, e), (None, None))


class ExtractSeasonEpisodeProperties(SimpleTestCase):
    @given(
        season=st.one_of(st.none(), st.integers(0, 500)),
        episode=st.one_of(st.none(), st.integers(0, 5000)),
        on_s=st.integers(0, 500),
        on_e=st.integers(0, 5000),
        d_s=st.integers(0, 500),
        d_e=st.integers(0, 5000),
    )
    def test_explicit_fields_win_then_onscreen_then_description(
        self, season, episode, on_s, on_e, d_s, d_e
    ):
        cp = {"season": season, "episode": episode,
              "onscreen_episode": f"S{on_s} E{on_e}"}
        s, e = extract_season_episode(cp, f"S{d_s}E{d_e} rest")
        self.assertEqual(s, season if season is not None else on_s)
        self.assertEqual(e, episode if episode is not None else on_e)

    @given(
        season=st.one_of(st.none(), st.integers(0, 500)),
        episode=st.one_of(st.none(), st.integers(0, 5000)),
        d_s=st.integers(0, 500),
        d_e=st.integers(0, 5000),
        onscreen=st.sampled_from([None, "", "Part 2", "E5"]),
    )
    def test_the_description_fills_only_the_missing_half(
        self, season, episode, d_s, d_e, onscreen
    ):
        cp = {"season": season, "episode": episode}
        if onscreen is not None:
            cp["onscreen_episode"] = onscreen  # present but unmatched
        s, e = extract_season_episode(cp, f"S{d_s}E{d_e} rest")
        self.assertEqual(s, season if season is not None else d_s)
        self.assertEqual(e, episode if episode is not None else d_e)


# ---------------------------------------------------------------------------
# extract_custom_properties / _programme_to_dict / _parse_programme_element
# ---------------------------------------------------------------------------

_TEXT_ALPHABET = string.ascii_letters + string.digits + " \t-_.:,;!?()[]#'\"/\\é"
xml_text = st.text(alphabet=_TEXT_ALPHABET, max_size=40)
_SYSTEMS = st.sampled_from(
    [None, "", "xmltv_ns", "onscreen", "dd_progid", "imdb.com", "thetvdb.com",
     "themoviedb.org", "SxxExx", "other"]
)
_SIMPLE_TAGS = st.sampled_from(
    ["category", "keyword", "date", "country", "language", "orig-language",
     "length", "premiere", "last-chance", "new", "live", "previously-shown",
     "review", "image", "title", "desc", "sub-title", "bogus"]
)


def _attr(name, value):
    return "" if value is None else f' {name}="{html.escape(value, quote=True)}"'


def _el(tag, text="", **attrs):
    a = "".join(_attr(k.replace("_", "-"), v) for k, v in attrs.items())
    return f"<{tag}{a}>{html.escape(text, quote=False)}</{tag}>"


children = st.lists(
    st.one_of(
        st.builds(lambda t, x: _el(t, x), _SIMPLE_TAGS, xml_text),
        st.builds(lambda s, x: _el("episode-num", x, system=s), _SYSTEMS, xml_text),
        st.builds(lambda x, s: "<rating" + _attr("system", s) + ">" + _el("value", x) + "</rating>",
                  xml_text, st.one_of(st.none(), xml_text)),
        st.builds(lambda x: "<star-rating>" + _el("value", x) + "</star-rating>", xml_text),
        st.builds(lambda t, x, r: "<credits>" + _el(t, x, role=r) + "</credits>",
                  st.sampled_from(["director", "actor", "writer", "presenter", "guest"]),
                  xml_text, st.one_of(st.none(), xml_text)),
        st.builds(lambda k, x: "<video>" + _el(k, x) + "</video>",
                  st.sampled_from(["present", "colour", "aspect", "quality"]), xml_text),
        st.builds(lambda x: "<audio>" + _el("stereo", x) + "</audio>", xml_text),
        st.builds(lambda t, x: "<subtitles" + _attr("type", t) + ">" + _el("language", x) + "</subtitles>",
                  st.one_of(st.none(), xml_text), xml_text),
        st.builds(lambda s: "<icon" + _attr("src", s) + "/>", st.one_of(st.none(), xml_text)),
        st.builds(lambda x, u: _el("length", x, units=u), xml_text,
                  st.one_of(st.none(), st.sampled_from(["minutes", "seconds"]))),
    ),
    max_size=14,
).map("".join)


def _programme(inner):
    return etree.fromstring(f"<programme>{inner}</programme>")


class ExtractCustomPropertiesProperties(SimpleTestCase):
    @given(inner=children)
    def test_any_wellformed_programme_yields_the_documented_types(self, inner):
        props = extract_custom_properties(_programme(inner))
        self.assertIsInstance(props, dict)
        for key in ("season", "episode"):
            if key in props:
                self.assertIsInstance(props[key], int)
        for key in ("categories", "keywords"):
            if key in props:
                self.assertTrue(props[key])
                for item in props[key]:
                    self.assertTrue(item)
                    self.assertEqual(item, item.strip())
        if "length" in props:
            self.assertIsInstance(props["length"]["value"], int)
            self.assertIsInstance(props["length"]["units"], str)

    # Totals-free form only: the XMLTV DTD also allows "s/total . e/total",
    # which int() refuses, so the season is silently dropped (plan I
    # finding F-3).
    @given(
        season=st.integers(0, 500),
        episode=st.integers(0, 5000),
        part=st.sampled_from(["", "0", "1"]),
        pad=st.sampled_from(["", " "]),
    )
    def test_xmltv_ns_is_zero_based_and_stored_one_based(
        self, season, episode, part, pad
    ):
        text = f"{pad}{season}{pad}.{pad}{episode}{pad}.{part}"
        props = extract_custom_properties(
            _programme(_el("episode-num", text, system="xmltv_ns"))
        )
        self.assertEqual(props["season"], season + 1)
        self.assertEqual(props["episode"], episode + 1)

    @given(
        ns_season=st.integers(0, 50),
        ns_episode=st.integers(0, 50),
        on_s=st.integers(0, 50),
        on_e=st.integers(0, 50),
        onscreen_first=st.booleans(),
    )
    def test_xmltv_ns_wins_over_onscreen_whatever_the_element_order(
        self, ns_season, ns_episode, on_s, on_e, onscreen_first
    ):
        ns = _el("episode-num", f"{ns_season}.{ns_episode}.", system="xmltv_ns")
        on = _el("episode-num", f"S{on_s}E{on_e}", system="onscreen")
        props = extract_custom_properties(_programme(on + ns if onscreen_first else ns + on))
        # xmltv_ns assigns unconditionally; onscreen only fills a missing key.
        self.assertEqual(props["season"], ns_season + 1)
        self.assertEqual(props["episode"], ns_episode + 1)
        self.assertEqual(props["onscreen_episode"], f"S{on_s}E{on_e}")

    @given(text=xml_text)
    def test_length_is_recorded_exactly_when_its_text_is_an_integer(self, text):
        props = extract_custom_properties(_programme(_el("length", text)))
        # int() also accepts single underscores between digits ("1_0" is 10).
        if re.fullmatch(r"\s*[+-]?\d+(?:_\d+)*\s*", text):
            self.assertEqual(props["length"], {"value": int(text), "units": "minutes"})
        else:
            self.assertNotIn("length", props)


class ProgrammeToDictProperties(SimpleTestCase):
    @given(
        inner=children,
        start=st.datetimes(timezones=st.just(dt_timezone.utc)),
        minutes=st.integers(0, 600),
    )
    def test_always_five_keys_with_string_text_and_iso_times(
        self, inner, start, minutes
    ):
        end = start + timedelta(minutes=minutes) if start.year < 9999 else start
        result = _programme_to_dict(_programme(inner), start, end)
        self.assertEqual(
            set(result), {"title", "description", "sub_title", "start_time", "end_time"}
        )
        for key in ("title", "description", "sub_title"):
            self.assertIsInstance(result[key], str)
        self.assertEqual(datetime.fromisoformat(result["start_time"]), start)
        self.assertEqual(datetime.fromisoformat(result["end_time"]), end)


_NAMED = ["eacute", "amp", "lt", "gt", "quot", "apos", "nbsp", "Uuml", "copy", "euro"]


class ParseProgrammeElementProperties(SimpleTestCase):
    @given(
        pieces=st.lists(
            st.one_of(
                st.text(alphabet=string.ascii_letters + " .", min_size=1, max_size=6),
                st.sampled_from(_NAMED).map(lambda n: f"&{n};"),
                # 0x7F-0x9F excluded: html.unescape remaps those per HTML5's
                # cp1252 table where XML keeps the code point; not this contract.
                st.integers(0x20, 0x2FFF).filter(lambda c: not 0x7F <= c <= 0x9F)
                .map(lambda c: f"&#{c};"),
            ),
            max_size=10,
        )
    )
    def test_html4_and_numeric_entities_resolve_as_html_unescape_does(self, pieces):
        text = "".join(pieces)
        elem = _parse_programme_element(
            f"<programme><title>{text}</title></programme>".encode()
        )
        self.assertEqual(elem.findtext("title") or "", html.unescape(text))

    @given(raw=st.one_of(
        st.binary(max_size=120),
        st.lists(st.sampled_from(
            [b"<programme>", b"</programme>", b"<title>", b"</title>", b"&", b";",
             b"&eacute;", b"&NewLine;", b"&#0;", b"&#xD800;", b"<", b">", b"x",
             b"\xff", b"]]>", b"<!--", b"<![CDATA["]), max_size=15).map(b"".join),
    ))
    def test_any_bytes_either_parse_or_raise_xml_syntax_error_only(self, raw):
        try:
            elem = _parse_programme_element(raw)
        except etree.XMLSyntaxError:
            return
        self.assertIsNotNone(elem)


# ---------------------------------------------------------------------------
# detect_file_format / validate_icon_url_fast
# ---------------------------------------------------------------------------

_FORMATS = {
    "gzip": (True, ".gz"), "zip": (True, ".zip"), "xz": (True, ".xz"),
    "xml": (False, ".xml"), "unknown": (False, ".tmp"),
}
_MAGIC = [(b"\x1f\x8b", "gzip"), (b"PK", "zip"), (b"\xfd7zXZ\x00", "xz")]
_EXTS = [(".gz", "gzip"), (".gzip", "gzip"), (".zip", "zip"), (".xz", "xz"),
         (".xml", "xml")]
_names = st.text(alphabet=string.ascii_letters + string.digits + "._-/", max_size=20)


class DetectFileFormatProperties(SimpleTestCase):
    @given(
        content=st.one_of(st.none(), st.binary(max_size=64)),
        path=st.one_of(st.none(), st.text(max_size=40)),
    )
    def test_the_result_is_always_a_consistent_vocabulary_triple(self, content, path):
        fmt, compressed, ext = detect_file_format(file_path=path, content=content)
        self.assertEqual((compressed, ext), _FORMATS[fmt])

    @given(
        magic=st.sampled_from(_MAGIC),
        tail=st.binary(max_size=40),
        name=_names,
        ext=st.sampled_from(_EXTS),
    )
    def test_magic_bytes_beat_any_extension(self, magic, tail, name, ext):
        prefix, expected = magic
        fmt, _, _ = detect_file_format(file_path=name + ext[0], content=prefix + tail)
        self.assertEqual(fmt, expected)

    @given(name=_names, ext=st.sampled_from(_EXTS), upper=st.booleans(),
           inner=st.sampled_from(["", ".xml", ".m3u", ".tar"]))
    def test_the_final_extension_decides_when_content_has_no_magic(
        self, name, ext, upper, inner
    ):
        suffix = inner + ext[0]
        path = name + (suffix.upper() if upper else suffix)
        fmt, _, _ = detect_file_format(file_path=path, content=b"not magic at all")
        self.assertEqual(fmt, ext[1])


class ValidateIconUrlFastProperties(_QuietTaskWarnings):
    @given(url=st.one_of(st.none(), st.text(max_size=300)), max_length=st.integers(1, 256))
    def test_none_exactly_when_the_url_exceeds_max_length(self, url, max_length):
        result = validate_icon_url_fast(url, max_length=max_length)
        if url and len(url) > max_length:
            self.assertIsNone(result)
        else:
            self.assertIs(result, url)

    @given(extra=st.integers(0, 50))
    def test_the_default_bound_is_the_model_field_max_length(self, extra):
        bound = EPGData._meta.get_field("icon_url").max_length
        self.assertEqual(validate_icon_url_fast("h" * bound), "h" * bound)
        self.assertIsNone(validate_icon_url_fast("h" * (bound + 1 + extra)))
```

#### `apps/epg/tests/test_property_text_query.py`

<!-- file: apps/epg/tests/test_property_text_query.py -->
```python
"""Property-based tests for ``parse_text_query`` (apps/epg/query_utils.py:35).

The shared search-expression parser behind the EPG search API
(apps/epg/api_views.py:262, :268), the DVR series-rule evaluator
(apps/channels/tasks.py:591, :598) and the recordings search
(apps/channels/api_views.py:4219, :4225). Its input is whatever a user types.

Two seed behaviours are deliberately kept out of these properties and are
reported in plan I's findings section rather than pinned (the first is
finding F-1; the second is noted there without a number):

* Text whose ``str.upper()`` is longer than itself (``\\u00df``, ``\\u0149``,
  ``\\ufb03``, ...) next to an operator word raises ``IndexError``: the
  operator scan finds positions in ``remaining.upper()`` and slices the
  original string with them. ``parse_text_query("title", "\\u00df a AND b")``
  raises. The no-raise properties therefore draw only length-preserving text.
* The docstring says regex mode treats the whole value as one regex, but the
  parser still splits it on parentheses and AND/OR (``(foo|bar) baz`` becomes
  two ``iregex`` lookups). Regex mode is only held to "never raises" here.

Closes the parse_text_query part of #202 (and duplicates #274, #158, #74).
"""

import re
import string

from django.db.models import Q
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.epg.query_utils import parse_text_query

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def _upper_preserves_length(s):
    return len(s.upper()) == len(s)


# Arbitrary user text plus operator-dense text, restricted to characters whose
# upper case has the same length (see the module docstring).
_OPS = st.sampled_from([" AND ", " OR ", " and ", " Or ", "(", ")", '"', " ", "x", "news"])
query_text = st.one_of(
    st.text(max_size=80),
    st.lists(st.one_of(_OPS, st.text(max_size=6)), max_size=20).map("".join),
).filter(_upper_preserves_length)

_WORD = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=12).filter(
    lambda w: w not in ("and", "or")
)
_PHRASE = st.lists(
    st.sampled_from(["AND", "OR", "and", "(", ")", "news", "tv", "x"]),
    min_size=1, max_size=6,
).map(" ".join)


def _leaves(q):
    return q.children


class ParseTextQueryProperties(SimpleTestCase):
    @given(raw=query_text, use_regex=st.booleans(), whole_words=st.booleans())
    def test_any_length_preserving_text_builds_a_q_without_raising(
        self, raw, use_regex, whole_words
    ):
        self.assertIsInstance(
            parse_text_query("title", raw, use_regex=use_regex, whole_words=whole_words),
            Q,
        )

    @given(
        term=st.text(max_size=30).filter(
            lambda t: t.strip() and not re.search(r"[()\"]| (and|or) ", t, re.I)
        )
    )
    def test_a_bare_term_is_one_icontains_on_its_stripped_text(self, term):
        q = parse_text_query("title", term)
        self.assertEqual(q.children, [("title__icontains", term.strip())])

    @given(a=_WORD, b=_WORD, op=st.sampled_from(["AND", "and", "And", "OR", "or"]))
    def test_a_binary_operator_joins_two_icontains_leaves(self, a, b, op):
        q = parse_text_query("title", f"{a} {op} {b}")
        self.assertEqual(q.connector, "AND" if op.upper() == "AND" else "OR")
        self.assertEqual(
            _leaves(q), [("title__icontains", a), ("title__icontains", b)]
        )

    @given(p1=_PHRASE, p2=_PHRASE)
    def test_double_quoted_phrases_stay_atomic_whatever_they_contain(self, p1, p2):
        q = parse_text_query("title", f'"{p1}" AND "{p2}"')
        self.assertEqual(q.connector, "AND")
        self.assertEqual(
            _leaves(q), [("title__icontains", p1), ("title__icontains", p2)]
        )

    @given(word=st.text(alphabet=string.ascii_letters, min_size=1, max_size=12))
    def test_whole_word_mode_matches_the_word_only_at_word_boundaries(self, word):
        q = parse_text_query("title", word, whole_words=True)
        ((lookup, pattern),) = q.children
        self.assertEqual(lookup, "title__iregex")
        # PostgreSQL's \y is Python's \b; check the pattern's meaning, not its text.
        py = re.compile(pattern.replace(r"\y", r"\b"), re.IGNORECASE)
        self.assertTrue(py.search(f"foo {word} bar"))
        self.assertTrue(py.search(f"{word.upper()}."))
        self.assertIsNone(py.search(f"foo{word}bar"))
```

#### `apps/epg/tests/test_property_sd_helpers.py`

<!-- file: apps/epg/tests/test_property_sd_helpers.py -->
```python
"""Property-based tests for the Schedules Direct helpers.

Surfaces (seed a54b09a9):

* ``sd_poster_cache_bust`` / ``sd_poster_proxy_path`` (apps/epg/utils.py:32, :44).
* ``sd_auth_lockout_seconds_for_code`` (apps/epg/sd_utils.py:81) - the /token
  cooldown table.
* ``sd_credential_fingerprint`` (:109) - clears a persisted lockout or cached
  token exactly when the credentials change.
* ``sd_auth_failure_message`` (:209) and ``sd_token_response_code`` (:266).
* ``sd_parse_response_payload`` (:691) - every SD HTTP body goes through it.
* ``_sd_pick_poster_url`` (apps/epg/sd_tasks.py:220) - picks a poster from
  SD's image list (called at :672 on provider JSON).

Closes the SD part of #202 (and duplicates #274, #158, #74).
"""

import json
import string

import requests
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.epg.sd_tasks import SD_POSTER_STYLE_CONFIG, _sd_pick_poster_url
from apps.epg.sd_utils import (
    SD_AUTH_LOCKOUT_CODES,
    SD_AUTH_LOCKOUT_SECONDS,
    SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK,
    SD_AUTH_LOCKOUT_SECONDS_SOFT,
    SD_AUTH_SOFT_CODES,
    SD_CODE_ACCOUNT_LOCKED,
    sd_auth_failure_message,
    sd_auth_lockout_seconds_for_code,
    sd_credential_fingerprint,
    sd_parse_response_payload,
    sd_token_response_code,
)
from apps.epg.utils import sd_poster_cache_bust, sd_poster_proxy_path

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# JSON values as json.loads produces them. Infinite floats are excluded:
# _sd_image_width's int() raises OverflowError on a JSON Infinity width
# (sd_tasks.py:140-143 catches only TypeError/ValueError) - plan I notes it as
# a minor finding; Schedules Direct is not a hostile source.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-10**6, 10**6)
    | st.floats(allow_infinity=False) | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=4)
    | st.dictionaries(st.text(max_size=8), inner, max_size=4),
    max_leaves=12,
)
_KNOWN_CODES = sorted(SD_AUTH_LOCKOUT_CODES)
codes = st.one_of(
    st.sampled_from(_KNOWN_CODES), st.integers(-10, 10000), st.none(),
    st.text(max_size=8), st.booleans(),
)


class SdPosterPathProperties(SimpleTestCase):
    @given(url=st.one_of(st.none(), st.text(max_size=120)), pid=st.integers(1, 10**12))
    def test_the_bust_is_twelve_hex_iff_there_is_a_url_and_the_path_carries_it(
        self, url, pid
    ):
        bust = sd_poster_cache_bust(url)
        path = sd_poster_proxy_path(pid, url)
        base = f"/api/epg/programs/{pid}/poster/"
        if not url:
            self.assertEqual(bust, "")
            self.assertEqual(path, base)
        else:
            self.assertRegex(bust, r"\A[0-9a-f]{12}\Z")
            self.assertEqual(bust, sd_poster_cache_bust(url))
            self.assertEqual(path, f"{base}?v={bust}")

    @given(a=st.text(min_size=1, max_size=60), b=st.text(min_size=1, max_size=60))
    def test_a_new_artwork_uri_gets_a_new_bust(self, a, b):
        if a != b:
            self.assertNotEqual(sd_poster_cache_bust(a), sd_poster_cache_bust(b))


class SdLockoutProperties(SimpleTestCase):
    @given(code=codes)
    def test_every_code_maps_to_its_documented_cooldown(self, code):
        seconds = sd_auth_lockout_seconds_for_code(code)
        if code == SD_CODE_ACCOUNT_LOCKED:
            expected = SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK
        elif code in SD_AUTH_SOFT_CODES:
            expected = SD_AUTH_LOCKOUT_SECONDS_SOFT
        else:
            expected = SD_AUTH_LOCKOUT_SECONDS
        self.assertEqual(seconds, expected)

    def test_the_cooldowns_are_ordered_locked_then_soft_then_default(self):
        self.assertLess(SD_AUTH_LOCKOUT_SECONDS_ACCOUNT_LOCK, SD_AUTH_LOCKOUT_SECONDS_SOFT)
        self.assertLess(SD_AUTH_LOCKOUT_SECONDS_SOFT, SD_AUTH_LOCKOUT_SECONDS)


_cred = st.one_of(st.none(), st.text(alphabet=string.printable, max_size=30))
_ws = st.text(alphabet=" \t\n", max_size=3)


class SdCredentialFingerprintProperties(SimpleTestCase):
    @given(user=_cred, password=_cred, lead=_ws, trail=_ws)
    def test_the_fingerprint_ignores_none_versus_empty_and_outer_whitespace(
        self, user, password, lead, trail
    ):
        fp = sd_credential_fingerprint(user, password)
        self.assertRegex(fp, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(
            fp,
            sd_credential_fingerprint(
                lead + (user or "") + trail, lead + (password or "") + trail
            ),
        )

    @given(
        user=st.text(alphabet=string.ascii_letters + string.digits, max_size=20),
        password=st.text(alphabet=string.ascii_letters + string.digits, max_size=20),
        edit=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=4),
    )
    def test_any_edit_to_either_credential_changes_the_fingerprint(
        self, user, password, edit
    ):
        fp = sd_credential_fingerprint(user, password)
        self.assertNotEqual(fp, sd_credential_fingerprint(user + edit, password))
        self.assertNotEqual(fp, sd_credential_fingerprint(user, password + edit))
        self.assertNotEqual(fp, sd_credential_fingerprint(edit + user, password))


class SdTokenCodeAndMessageProperties(SimpleTestCase):
    @given(body=json_values)
    def test_the_token_code_is_the_int_code_or_zero_for_any_json_body(self, body):
        code = sd_token_response_code(body)
        self.assertIsInstance(code, int)
        if isinstance(body, dict) and isinstance(body.get("code"), int):
            self.assertEqual(code, body["code"])
        else:
            self.assertEqual(code, 0)

    @given(code=codes, sd_message=st.one_of(st.none(), st.text(max_size=40)))
    def test_the_failure_message_is_fixed_for_known_codes_and_echoes_unknown_ones(
        self, code, sd_message
    ):
        msg = sd_auth_failure_message(code, sd_message)
        self.assertIsInstance(msg, str)
        self.assertTrue(msg)
        if code in SD_AUTH_LOCKOUT_CODES:
            self.assertEqual(msg, sd_auth_failure_message(code, None))
        else:
            self.assertIn(f"(code {code})", msg)
            if sd_message:
                self.assertTrue(msg.endswith(sd_message))


def _response(body, content_type):
    r = requests.Response()
    r.status_code = 200
    r._content = body
    if content_type is not None:
        r.headers["Content-Type"] = content_type
    r.encoding = None
    return r


class SdParseResponsePayloadProperties(SimpleTestCase):
    @given(
        body=st.one_of(
            st.binary(max_size=80),
            json_values.map(lambda v: json.dumps(v).encode()),
        ),
        content_type=st.sampled_from(
            [None, "", "application/json", "text/html", "APPLICATION/JSON; charset=utf-8"]
        ),
    )
    def test_any_body_yields_a_dict_and_its_int_code_or_nothing(self, body, content_type):
        code, data = sd_parse_response_payload(_response(body, content_type))
        if data is None:
            self.assertIsNone(code)
            return
        self.assertIsInstance(data, dict)
        self.assertEqual(data, json.loads(body))
        self.assertEqual(code, data["code"] if isinstance(data.get("code"), int) else None)

    @given(payload=st.dictionaries(st.text(max_size=8), json_values, max_size=4),
           code=st.integers(-10, 10000))
    def test_a_json_object_body_round_trips_with_its_code(self, payload, code):
        payload = dict(payload, code=code)
        got_code, data = sd_parse_response_payload(
            _response(json.dumps(payload).encode(), "text/plain")
        )
        self.assertEqual((got_code, data), (code, payload))

    def test_no_response_is_nothing(self):
        self.assertEqual(sd_parse_response_payload(None), (None, None))


_image = st.dictionaries(
    st.sampled_from(["uri", "category", "aspect", "width", "primary", "height"]),
    st.one_of(
        json_values,
        st.sampled_from(["Iconic", "Banner-L1", "Box Art", "2x3", "3x4", "16x9", "1x1",
                         "true", "True", "0", "240", "1920"]),
    ),
    max_size=6,
)
_styles = st.sampled_from(sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended", "bogus", None])


class SdPickPosterUrlProperties(SimpleTestCase):
    @given(images=st.lists(st.one_of(_image, json_values), max_size=8), style=_styles)
    def test_the_pick_is_none_or_a_uri_taken_from_the_input(self, images, style):
        uri = _sd_pick_poster_url(images, style)
        if uri is None:
            return
        self.assertIn(
            uri, [img.get("uri") for img in images if isinstance(img, dict) and img.get("uri")]
        )

    @given(
        others=st.lists(_image, max_size=6),
        aspect=st.sampled_from(["2x3", "3x4"]),
        width=st.integers(240, 4000),
    )
    def test_a_primary_poster_category_image_is_always_found(self, others, aspect, width):
        # Any primary image in a poster category with a uri is reachable by
        # every style's fallback chain (recommended tier 1; configured styles'
        # "SD primary among poster categories" fallback).
        target = {"uri": "wanted", "category": "Iconic", "aspect": aspect,
                  "width": width, "primary": "true"}
        # A loop with msg=, not subTest: Hypothesis disables subTest under @given.
        for style in sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended"]:
            self.assertIsNotNone(_sd_pick_poster_url(others + [target], style), msg=style)

    def test_an_empty_list_is_no_poster_for_every_style(self):
        for style in sorted(SD_POSTER_STYLE_CONFIG) + ["sd_recommended", "bogus"]:
            with self.subTest(style=style):
                self.assertIsNone(_sd_pick_poster_url([], style))
```


### Appendix B: PR I-2, m3u

#### `apps/m3u/tests/test_property_m3u_parsing.py`

<!-- file: apps/m3u/tests/test_property_m3u_parsing.py -->
```python
"""Property tests for the M3U ingest parsing surfaces (issues #218, #69).

Surfaces, with their line at seed a54b09a9:

- ``parse_extinf_line`` (``apps/m3u/tasks.py:598``)
- ``iter_m3u_entries`` (``apps/m3u/tasks.py:644``)
- ``get_case_insensitive_attr`` (``apps/m3u/tasks.py:590``)
- ``_open_m3u_text_source`` (``apps/m3u/tasks.py:169``), fed arbitrary bytes
  through ``iter_m3u_entries`` -- the #217 seam: it holds only once C-3 decodes
  invalid UTF-8 instead of raising ``UnicodeDecodeError``.
- ``normalize_stream_url`` (``apps/m3u/utils.py:37``)
- ``parse_is_adult`` (``apps/m3u/utils.py:25``)

Provider playlists are untrusted input: every property here is either a
"never raises" totality claim or a round trip of a structure the generator
built, so the oracle is the generator, never the parser.
"""

import gzip
import lzma
import os
import string
import tempfile

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _open_m3u_text_source,
    get_case_insensitive_attr,
    iter_m3u_entries,
    parse_extinf_line,
)
from apps.m3u.utils import normalize_stream_url, parse_is_adult

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Provider-flavoured half-valid text plus full unicode.
garbage_text = st.text(max_size=200) | st.text(
    alphabet='0123456789abcxyz-_ =",\'#EXTINF:tvgloghd.', max_size=200
)
attr_keys = st.text(
    alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=12
)
# Attribute values: no quote of either style and no line break.
attr_values = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters="\"'\n\r"
    ),
    max_size=30,
)
# Display names: no line break, and no '=' or quote so the attribute regex
# cannot legitimately extend into them.
display_names = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",), blacklist_characters="\n\r=\"'"
    ),
    max_size=40,
)
url_tails = st.text(
    alphabet=string.ascii_letters + string.digits + "/._-", min_size=1, max_size=20
)


@st.composite
def extinf_lines(draw):
    """An #EXTINF line, the attributes it carries (keys lowercased), and its display name."""
    attrs = {}
    rendered = []
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        key = draw(attr_keys)
        if key.lower() in attrs:
            continue  # last-write-wins makes a duplicate key unobservable
        value = draw(attr_values)
        quote = draw(st.sampled_from(('"', "'")))
        attrs[key.lower()] = value
        rendered.append(f"{key}={quote}{value}{quote}")
    display = draw(display_names)
    content = f"-1 {' '.join(rendered)},{display}" if rendered else f"-1,{display}"
    return "#EXTINF:" + content, attrs, display


class ParseExtinfLineProperties(SimpleTestCase):
    @given(line=garbage_text)
    def test_parse_extinf_line_is_total_and_none_exactly_without_the_prefix(self, line):
        parsed = parse_extinf_line(line)
        if not line.startswith("#EXTINF:"):
            self.assertIsNone(parsed)
            return
        self.assertEqual(set(parsed), {"attributes", "display_name", "name"})
        for key in parsed["attributes"]:
            self.assertEqual(key, key.lower())
        self.assertIsInstance(parsed["name"], str)
        self.assertIsInstance(parsed["display_name"], str)

    @given(drawn=extinf_lines())
    def test_generated_attributes_and_display_name_round_trip(self, drawn):
        line, attrs, display = drawn
        parsed = parse_extinf_line(line)
        self.assertEqual(parsed["attributes"], attrs)
        self.assertEqual(parsed["display_name"], display.strip())
        if display.strip():
            # The comma text is the canonical title (base #EXTINF spec).
            self.assertEqual(parsed["name"], display.strip())

    @given(content=st.text(max_size=80).filter(lambda s: s.strip() and "\n" not in s))
    def test_name_is_never_empty_for_non_blank_content(self, content):
        # The four-way fallback ends in ``content.strip()``.
        self.assertTrue(parse_extinf_line("#EXTINF:" + content)["name"])


class IterM3uEntriesProperties(SimpleTestCase):
    @given(lines=st.lists(garbage_text, max_size=60))
    def test_iter_m3u_entries_is_total_and_every_entry_has_a_url(self, lines):
        for entry in iter_m3u_entries(lines):
            self.assertIsInstance(entry["url"], str)
            self.assertIsInstance(entry["attributes"], dict)
            self.assertIsInstance(entry["name"], str)

    @given(
        names=st.lists(display_names, min_size=1, max_size=8),
        scheme=st.sampled_from(("http", "https", "rtsp", "rtp")),
        tails=st.lists(url_tails, min_size=8, max_size=8),
    )
    def test_each_extinf_url_pair_yields_exactly_one_entry_in_order(self, names, scheme, tails):
        lines = []
        for name, tail in zip(names, tails):
            lines += [f"#EXTINF:-1,{name}", f"{scheme}://host/{tail}"]
        entries = list(iter_m3u_entries(lines))
        self.assertEqual(
            [e["url"] for e in entries],
            [f"{scheme}://host/{t}" for t in tails[: len(names)]],
        )

    @given(names=st.lists(display_names, min_size=2, max_size=5), tail=url_tails)
    def test_an_extinf_without_a_url_is_discarded_by_the_next_extinf(self, names, tail):
        lines = [f"#EXTINF:-1,{n}" for n in names] + [f"http://host/{tail}"]
        with self.assertLogs("apps.m3u.tasks", level="WARNING"):
            entries = list(iter_m3u_entries(lines))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["display_name"], names[-1].strip())

    @given(
        group=st.text(alphabet=string.ascii_letters + " -_", max_size=20),
        vlc_opt=st.text(alphabet=string.ascii_letters + "=-/.", max_size=20),
        explicit=st.booleans(),
        tail=url_tails,
    )
    def test_extgrp_fills_group_title_only_when_absent_and_extvlcopt_attaches(
        self, group, vlc_opt, explicit, tail
    ):
        extinf = '#EXTINF:-1 group-title="Explicit",N' if explicit else "#EXTINF:-1,N"
        lines = [extinf, f"#EXTGRP:{group}", f"#EXTVLCOPT:{vlc_opt}", f"http://host/{tail}"]
        (entry,) = list(iter_m3u_entries(lines))
        expected_group = "Explicit" if explicit else group.strip()
        self.assertEqual(entry["attributes"]["group-title"], expected_group)
        self.assertEqual(entry["vlc_opts"], [vlc_opt.strip()])


# Names built from characters a Latin-1 or Windows-1252 provider sends: every
# one of them is a byte >= 0xA0 once encoded, i.e. invalid as a lone UTF-8
# byte, so a strict UTF-8 decode of the playlist raises.
latin1_names = st.text(
    alphabet=string.ascii_letters + " " + "".join(chr(c) for c in range(0xA0, 0x100)),
    min_size=1,
    max_size=20,
)


def _write(tmpdir, suffix, data):
    path = os.path.join(tmpdir, "playlist.m3u" + suffix)
    opener = {"": open, ".gz": gzip.open, ".xz": lzma.open}[suffix]
    with opener(path, "wb") as fh:
        fh.write(data)
    return path


class OpenM3uTextSourceProperties(SimpleTestCase):
    """#217 seam: holds after C-3 decodes invalid byte runs instead of raising."""

    @given(
        data=st.binary(max_size=400),
        suffix=st.sampled_from(("", ".gz", ".xz")),
    )
    # #217: a Latin-1 playlist raised UnicodeDecodeError ... byte 0xe9.
    @example(data="#EXTINF:-1,TF1 Séries HD\nhttp://h/1\n".encode("latin-1"), suffix="")
    def test_arbitrary_playlist_bytes_never_raise_on_any_compression(self, data, suffix):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, suffix, data)
            with _open_m3u_text_source(path) as fh:
                for entry in iter_m3u_entries(fh):
                    self.assertIsInstance(entry["url"], str)

    @given(
        names=st.lists(latin1_names, min_size=1, max_size=6),
        suffix=st.sampled_from(("", ".gz", ".xz")),
    )
    def test_a_latin1_playlist_yields_one_entry_per_url(self, names, suffix):
        body = "".join(f"#EXTINF:-1,{n}\nhttp://host/{i}\n" for i, n in enumerate(names))
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write(tmpdir, suffix, body.encode("latin-1"))
            with _open_m3u_text_source(path) as fh:
                urls = [e["url"] for e in iter_m3u_entries(fh)]
        self.assertEqual(urls, [f"http://host/{i}" for i in range(len(names))])


class GetCaseInsensitiveAttrProperties(SimpleTestCase):
    @given(
        key=attr_keys,
        value=st.text(max_size=20),
        noise=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
        spelling=st.sampled_from((str.upper, str.lower, str.swapcase)),
    )
    def test_a_present_key_is_found_whatever_its_case(self, key, value, noise, spelling):
        noise = {k: v for k, v in noise.items() if k.lower() != key.lower()}
        attributes = {**noise, spelling(key): value}
        self.assertEqual(get_case_insensitive_attr(attributes, key), value)

    @given(
        attributes=st.dictionaries(attr_keys, st.text(max_size=10), max_size=5),
        default=st.text(min_size=1, max_size=10),
    )
    def test_an_absent_key_returns_the_supplied_default(self, attributes, default):
        attributes = {k: v for k, v in attributes.items() if k.lower() != "tvg-id"}
        self.assertEqual(get_case_insensitive_attr(attributes, "tvg-ID", default), default)


class NormalizeStreamUrlProperties(SimpleTestCase):
    @given(url=st.none() | garbage_text | garbage_text.map(lambda s: "udp://@" + s))
    def test_only_a_leading_vlc_udp_at_is_removed_and_only_once(self, url):
        result = normalize_stream_url(url)
        if url and url.startswith("udp://@"):
            self.assertEqual(result, "udp://" + url[len("udp://@"):])
        else:
            self.assertEqual(result, url)


class ParseIsAdultProperties(SimpleTestCase):
    json_values = st.recursive(
        st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=10),
        lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=3), inner, max_size=3),
        max_leaves=6,
    )

    @given(value=json_values)
    def test_parse_is_adult_is_total_over_provider_json(self, value):
        self.assertIsInstance(parse_is_adult(value), bool)

    @given(
        n=st.integers(min_value=-5, max_value=5),
        render=st.sampled_from((lambda n: n, str, lambda n: f" {n} ")),
    )
    def test_true_exactly_for_one_as_int_or_string(self, n, render):
        self.assertEqual(parse_is_adult(render(n)), n == 1)
```

#### `apps/m3u/tests/test_property_backreferences.py`

<!-- file: apps/m3u/tests/test_property_backreferences.py -->
```python
"""Property tests for ``convert_js_numbered_backreferences`` (issues #218, #69; seam #171).

Surface at seed a54b09a9: ``apps/m3u/utils.py:13``. The helper turns a
JavaScript-style replacement template (``$1``) into a Python ``regex``
template, and the auto-sync rename feeds the result to ``regex.sub``
(``apps/m3u/tasks.py:2608``). These properties exercise it the way the rename
does -- ``regex.sub(pattern, convert(template), target)`` -- because the
defect (#171) is what the converted template *does*, not what it looks like.

Both properties hold under either reading of ``$0`` that C-4 offers the user
(literal ``$0``, the default, or the whole match), so they do not depend on
that ruling:

1. The output contains no character that is in neither the target nor the
   template. Before C-4, ``$0`` became ``\\0`` (a NUL byte) and ``$01`` became
   ``\\01`` (U+0001).
2. For templates whose tokens are ``$N`` or ``$0N`` with 1 <= N <= the group
   count, and whose next literal character is not a digit, the output equals
   a hand-written model of JavaScript's ``String.prototype.replace`` with a
   global regex (ECMA-262 GetSubstitution): ``$N`` is group N's text, or ""
   when the group did not participate. The model uses ``regex.finditer`` only
   to find matches; it never calls the helper under test.

C-4's adopted rule is ``\$(0[1-9]|[1-9]\d?)`` -> ``\g<N>``, JavaScript's own
``$n``/``$nn`` grammar: at most two digits after ``$``, and a leading zero only
as ``$0n``. ``test_multi_digit_tokens_read_exactly_as_javascript_does`` pins
the multi-digit cases against outputs recorded from Node 22's
``String.prototype.replace`` (the oracle is a table of constants, not the
code under test). The one remaining divergence is JavaScript's fallback
when group ``nn`` does not exist (``$10`` with two groups reads ``$1`` then
``0``); the helper refuses it instead, and C-4 records that as pre-existing,
so it is not asserted here.
"""

import regex
from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.utils import convert_js_numbered_backreferences

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# (pattern, group count). Fixed, simple patterns on which JavaScript and the
# ``regex`` module agree about what matches; the property is about the
# replacement template, not the regex engine.
PATTERNS = [
    (r"(a)", 1),
    (r"(a)(b)", 2),
    (r"(.)(.)?", 2),
    (r"(.*)$", 1),
    (r"(h)/(u)", 2),
    (r"([a-z]+)-(\d+)?", 2),
]
targets = st.text(alphabet="abhu/-0123456789xy", max_size=24)
# Templates as the operator types them: literals, digits and ``$``, but no
# backslash (a JS template has no backslash escapes; that is outside #171).
templates = st.text(alphabet="ab/-[]$0123456789x", max_size=16)


def _apply(pattern, template, target):
    """The rename's call shape. ``None`` means the template was rejected."""
    try:
        return regex.sub(pattern, convert_js_numbered_backreferences(template), target)
    except (regex.error, IndexError):
        return None  # an invalid group number is refused, not corrupted


@st.composite
def js_templates(draw, group_count):
    """A template of literal runs and ``$N``/``$0N`` tokens, N in 1..group_count.

    A literal run following a token never starts with a digit: JavaScript
    would read that digit as part of a two-digit group number, a divergence
    C-4 documents and does not change.
    """
    pieces = []
    for _ in range(draw(st.integers(min_value=0, max_value=5))):
        if draw(st.booleans()):
            n = draw(st.integers(min_value=1, max_value=group_count))
            zero = draw(st.sampled_from(("", "0")))
            pieces.append(("group", n, f"${zero}{n}"))
        else:
            first = draw(st.sampled_from("ab/-[]x"))
            rest = draw(st.text(alphabet="ab/-[]x0123456789", max_size=4))
            pieces.append(("literal", None, first + rest))
    return pieces


def _javascript_replace(pattern, pieces, target):
    out = []
    last = 0
    for m in regex.finditer(pattern, target):
        out.append(target[last:m.start()])
        for kind, n, text in pieces:
            out.append((m.group(n) or "") if kind == "group" else text)
        last = m.end()
    out.append(target[last:])
    return "".join(out)


class JsBackreferenceConversionProperties(SimpleTestCase):
    @given(case=st.sampled_from(PATTERNS), template=templates, target=targets)
    # #171: transform_url("/", r"(.*)$", "$0") returned '\x00\x00'.
    @example(case=(r"(.*)$", 1), template="$0", target="/")
    # #171: "$01" became "\01", a U+0001 control byte.
    @example(case=(r"(h)/(u)", 2), template="$01/$2", target="http://h/u/p/1.ts")
    def test_conversion_never_introduces_a_character_absent_from_target_and_template(
        self, case, template, target
    ):
        pattern, _ = case
        result = _apply(pattern, template, target)
        if result is None:
            return
        self.assertLessEqual(set(result), set(target) | set(template), repr(result))

    @given(data=st.data(), case=st.sampled_from(PATTERNS), target=targets)
    @example(
        data=None,
        case=(r"(h)/(u)", 2),
        target="http://h/u/p/1.ts",
    ).via("#171: $02-$01 must read groups 2 and 1, not octal escapes")
    def test_group_tokens_substitute_like_javascript_string_replace(self, data, case, target):
        pattern, group_count = case
        if data is None:
            pieces = [("group", 2, "$02"), ("literal", None, "-"), ("group", 1, "$01")]
        else:
            pieces = data.draw(js_templates(group_count))
        template = "".join(text for _, _, text in pieces)
        self.assertEqual(
            _apply(pattern, template, target),
            _javascript_replace(pattern, pieces, target),
            f"template={template!r}",
        )

    # "abcdefghijkl".replace(TWELVE_GROUPS, template), recorded in Node 22.
    TWELVE_GROUPS = r"(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)(l)"
    NODE_22_OUTPUTS = [
        ("$012", "a2"),  # $01 then a literal 2, not group 12
        ("$001", "$001"),  # no $0 token, and $00 is not a group
        ("$0012", "$0012"),
        ("[$100]", "[j0]"),  # at most two digits: $10 then a literal 0
        ("$12", "l"),
        ("$01", "a"),
        ("$1x", "ax"),
        ("$010", "a0"),
    ]

    def test_multi_digit_tokens_read_exactly_as_javascript_does(self):
        for template, expected in self.NODE_22_OUTPUTS:
            with self.subTest(template=template):
                self.assertEqual(
                    _apply(self.TWELVE_GROUPS, template, "abcdefghijkl"), expected
                )
```

#### `apps/m3u/tests/test_property_credentials.py`

<!-- file: apps/m3u/tests/test_property_credentials.py -->
```python
"""Property tests for the credential helpers behind the shared connection pool
(issues #218, #69; seam #68).

Surfaces, with their line at seed a54b09a9:

- ``compute_credential_fingerprint`` (``apps/m3u/connection_pool.py:49``). It
  groups accounts that share one IPTV login so they share one cap. The
  username is case-insensitive and the password is not.
- ``extract_credentials_from_stream_url`` (``apps/m3u/connection_pool.py:57``).
  It parses ``/live|movie|series/<user>/<pass>/`` out of an Xtream stream URL.

The #68 seam: the seed normalises the username with ``.lower()``, which is not
a caseless match. ``'µ'`` (U+00B5) upper-cases to U+039C, which lower-cases to
U+03BC. So the two spellings of one login fingerprint differently and escape
the shared cap. C-5 switches to ``.casefold()``.
"""

import string

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.connection_pool import (
    compute_credential_fingerprint,
    extract_credentials_from_stream_url,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

credentials = st.text(max_size=40)
# A username that Unicode's default caseless matching treats as the same login
# as its upper-case spelling. This excludes the few code points where upper()
# is not caseless-equivalent (e.g. dotless 'ı' upper-cases to 'I', which
# folds to 'i'), where no case-insensitive grouping is correct. The filter
# restricts the domain only; the assertion is on the fingerprint.
caseless_usernames = st.text(min_size=1, max_size=30).filter(
    lambda u: u.strip() and u.upper().casefold() == u.casefold()
)
passwords = st.text(min_size=1, max_size=30).filter(lambda p: p.strip())


class CredentialFingerprintProperties(SimpleTestCase):
    @given(username=st.none() | credentials, password=st.none() | credentials)
    def test_fingerprint_is_deterministic_hex_or_none_exactly_when_a_credential_is_blank(
        self, username, password
    ):
        fp = compute_credential_fingerprint(username, password)
        self.assertEqual(fp, compute_credential_fingerprint(username, password))
        if not username or not password:
            self.assertIsNone(fp)
        else:
            self.assertRegex(fp, r"^[0-9a-f]{64}$")

    @given(
        username=caseless_usernames,
        password=passwords,
        spelling=st.sampled_from((str.upper, str.lower, str.swapcase)),
        pad=st.sampled_from(("", " ", "  \t")),
    )
    # #68 (and #69's shrink, 'μ'): the micro sign and its upper-case spelling
    # fingerprinted differently under .lower().
    @example(username="µ", password="0", spelling=str.upper, pad="")
    def test_case_and_surrounding_whitespace_variants_of_a_username_share_a_fingerprint(
        self, username, password, spelling, pad
    ):
        self.assertEqual(
            compute_credential_fingerprint(username, password),
            compute_credential_fingerprint(pad + spelling(username) + pad, password),
        )

    @given(
        username=st.text(alphabet=string.ascii_letters, min_size=1, max_size=10),
        password=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=20).filter(
            lambda p: p.swapcase() != p
        ),
    )
    def test_a_password_differing_only_in_case_is_a_different_login(self, username, password):
        self.assertNotEqual(
            compute_credential_fingerprint(username, password),
            compute_credential_fingerprint(username, password.swapcase()),
        )


segment = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="/"),
    min_size=1,
    max_size=20,
)


class ExtractCredentialsProperties(SimpleTestCase):
    @given(url=st.text(max_size=200))
    def test_extraction_is_total_and_both_or_neither(self, url):
        user, password = extract_credentials_from_stream_url(url)
        if user is None:
            self.assertIsNone(password)
        else:
            self.assertNotIn("/", user)
            self.assertNotIn("/", password)
            self.assertTrue(user and password)

    @given(
        user=segment,
        password=segment,
        kind=st.sampled_from(("live", "movie", "series", "LIVE", "Movie")),
        host=st.sampled_from(("http://h", "https://h.example:8080", "http://h/sub")),
        tail=st.sampled_from(("1.ts", "99999.m3u8", "7.mkv")),
    )
    def test_xtream_url_round_trips_user_and_password(self, user, password, kind, host, tail):
        url = f"{host}/{kind}/{user}/{password}/{tail}"
        self.assertEqual(extract_credentials_from_stream_url(url), (user, password))

    @given(path=st.text(alphabet=string.ascii_letters + "/.", max_size=40))
    def test_a_url_without_a_kind_segment_yields_no_credentials(self, path):
        url = "http://h/" + path.replace("live", "").replace("movie", "").replace("series", "")
        self.assertEqual(extract_credentials_from_stream_url(url), (None, None))
```

#### `apps/m3u/tests/test_property_numbering.py`

<!-- file: apps/m3u/tests/test_property_numbering.py -->
```python
"""Property tests for auto-sync channel numbering and the batch-count summary
(issues #218, #145, #69).

Surfaces, with their line at seed a54b09a9:

- ``_next_available_number`` (``apps/m3u/tasks.py:1907``): the smallest free
  integer at or above ``start``, or ``None`` when an inclusive ``end`` is
  exhausted.
- ``_pick_target_number`` (``apps/m3u/tasks.py:1927``): the per-mode claim,
  whose docstring states each mode's contract.
- ``_batch_stream_count_message`` / ``_parse_batch_stream_counts``
  (``apps/m3u/tasks.py:1070``, ``:1077``): the batch workers' summary string
  and the parser that totals it.

Every oracle below is a brute-force scan over a small integer range, written
in the test, never a call back into the helper.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import (
    _batch_stream_count_message,
    _next_available_number,
    _parse_batch_stream_counts,
    _pick_target_number,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

used_sets = st.sets(st.integers(min_value=-5, max_value=60), max_size=50)
starts = st.integers(min_value=-5, max_value=40)
ends = st.none() | st.integers(min_value=-5, max_value=60)


def _brute_force_next(used, start, end):
    """Smallest n >= start not in used, or None past an inclusive end."""
    n = start
    while True:
        if end is not None and n > end:
            return None
        if n not in used:
            return n
        n += 1


class NextAvailableNumberProperties(SimpleTestCase):
    @given(used=used_sets, start=starts, end=ends)
    def test_next_available_is_the_smallest_free_number_within_the_bound(self, used, start, end):
        self.assertEqual(
            _next_available_number(used, start, end=end),
            _brute_force_next(used, start, end),
        )

    @given(start=st.integers(min_value=0, max_value=40), span=st.integers(min_value=0, max_value=20))
    def test_none_exactly_when_the_inclusive_range_is_full(self, start, span):
        end = start + span
        full = set(range(start, end + 1))
        self.assertIsNone(_next_available_number(full, start, end=end))
        self.assertEqual(_next_available_number(full - {end}, start, end=end), end)


streams = st.builds(SimpleNamespace, stream_chno=st.none() | st.integers(min_value=1, max_value=60))
modes = st.sampled_from(("provider", "next_available", "fixed"))


class PickTargetNumberProperties(SimpleTestCase):
    @given(
        mode=modes,
        stream=streams,
        used=used_sets,
        cursor=st.integers(min_value=1, max_value=40),
        fallback=st.integers(min_value=1, max_value=40),
        end=ends,
    )
    def test_no_mode_ever_claims_a_used_number(self, mode, stream, used, cursor, fallback, end):
        result = _pick_target_number(mode, stream, used, cursor, fallback, end_number=end)
        if result is not None:
            self.assertNotIn(result, used)

    @given(stream=streams, used=used_sets, fallback=st.integers(min_value=1, max_value=40), end=ends)
    def test_provider_mode_uses_a_free_provider_number_verbatim_else_falls_back_in_range(
        self, stream, used, fallback, end
    ):
        result = _pick_target_number("provider", stream, used, 1, fallback, end_number=end)
        if stream.stream_chno is not None and stream.stream_chno not in used:
            # End bounds only the fallback: a free provider number is used as-is.
            self.assertEqual(result, stream.stream_chno)
        else:
            self.assertEqual(result, _brute_force_next(used, fallback, end))

    @given(used=used_sets, cursor=st.integers(min_value=1, max_value=40), end=st.integers(min_value=-5, max_value=60))
    def test_next_available_mode_starts_at_one_and_ignores_end(self, used, cursor, end):
        result = _pick_target_number(
            "next_available", SimpleNamespace(stream_chno=None), used, cursor, 99, end_number=end
        )
        self.assertEqual(result, _brute_force_next(used, 1, None))

    @given(used=used_sets, cursor=st.integers(min_value=1, max_value=40), end=ends)
    def test_fixed_mode_counts_up_from_the_cursor_bounded_by_end(self, used, cursor, end):
        result = _pick_target_number(
            "fixed", SimpleNamespace(stream_chno=5), used, cursor, 99, end_number=end
        )
        self.assertEqual(result, _brute_force_next(used, cursor, end))


class BatchStreamCountProperties(SimpleTestCase):
    counts = st.integers(min_value=0, max_value=10**9)

    @given(created=counts, updated=counts, unchanged=counts)
    def test_a_built_summary_parses_back_to_its_counts(self, created, updated, unchanged):
        message = _batch_stream_count_message(created, updated, unchanged)
        self.assertEqual(_parse_batch_stream_counts(message), (created, updated, unchanged))

    @given(value=st.none() | st.integers() | st.lists(st.integers(), max_size=3) | st.binary(max_size=10))
    def test_non_string_results_count_as_zero(self, value):
        self.assertEqual(_parse_batch_stream_counts(value), (0, 0, 0))

    @given(text=st.text(max_size=120))
    def test_arbitrary_text_is_total_and_all_or_nothing(self, text):
        parsed = _parse_batch_stream_counts(text)
        self.assertEqual(len(parsed), 3)
        self.assertTrue(all(isinstance(n, int) and n >= 0 for n in parsed))
        if "created" not in text or "updated" not in text or "unchanged" not in text:
            # A missing counter zeroes all three rather than returning a partial count.
            self.assertEqual(parsed, (0, 0, 0))
```

#### `apps/m3u/tests/test_property_stream_filters.py`

<!-- file: apps/m3u/tests/test_property_stream_filters.py -->
```python
"""Property tests for M3U stream filtering (issue #145; seam #262).

Surfaces, with their line at seed a54b09a9:

- ``_compile_m3u_stream_filters`` (``apps/m3u/tasks.py:1017``)
- ``_stream_passes_m3u_filters`` (``apps/m3u/tasks.py:1030``): the first
  filter whose target field matches decides the outcome, as
  ``not filter.exclude``. A stream that no filter matches passes.

The oracle is stdlib ``re`` over a fixed set of benign patterns, on which
``re`` and ``regex`` agree, applied by a first-match loop written here. The
properties survive C-3's #262 change, which moves compilation to ``regex``
with a per-search timeout and keeps ``.search`` and ``.pattern`` on the
compiled object. They assert nothing about timing. They generate no
pathological pattern, because C-3 makes a timed-out filter non-matching and
that is C-3's own example test to pin.
"""

import re
from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import _compile_m3u_stream_filters, _stream_passes_m3u_filters

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

PATTERNS = ["news", "Sport", "hd$", "^uk", r"\d+", "adult|xxx", "[A-Z]{2}", "x"]
fields = st.none() | st.text(alphabet="newsSportHDhduUkKaltxXX0123 |/:.", max_size=30)
filters = st.builds(
    SimpleNamespace,
    filter_type=st.sampled_from(("name", "url", "group", "other")),
    exclude=st.booleans(),
    regex_pattern=st.sampled_from(PATTERNS),
    custom_properties=st.sampled_from(
        (None, {}, {"case_sensitive": True}, {"case_sensitive": False})
    ),
)


def _expected(name, url, group, filter_objs):
    """First-match-decides, re-derived from the documented contract."""
    for f in filter_objs:
        flags = re.IGNORECASE if (f.custom_properties or {}).get("case_sensitive", True) is False else 0
        target = {"url": url, "group": group}.get(f.filter_type, name)
        if re.search(f.regex_pattern, target or "", flags):
            return not f.exclude
    return True


class StreamPassesM3UFiltersProperties(SimpleTestCase):
    @given(name=fields, url=fields, group=fields)
    def test_with_no_filters_every_stream_passes(self, name, url, group):
        self.assertIs(_stream_passes_m3u_filters(name, url, group, []), True)

    @given(name=fields, url=fields, group=fields, filter_objs=st.lists(filters, min_size=1, max_size=4))
    def test_the_first_matching_filter_decides_by_its_exclude_flag(self, name, url, group, filter_objs):
        compiled = _compile_m3u_stream_filters(filter_objs)
        self.assertEqual(
            _stream_passes_m3u_filters(name, url, group, compiled),
            _expected(name, url, group, filter_objs),
        )

    @given(name=fields, url=fields, group=fields, filter_objs=st.lists(filters, min_size=1, max_size=4))
    def test_include_only_filters_never_reject(self, name, url, group, filter_objs):
        for f in filter_objs:
            f.exclude = False
        compiled = _compile_m3u_stream_filters(filter_objs)
        self.assertIs(_stream_passes_m3u_filters(name, url, group, compiled), True)
```

#### `apps/m3u/tests/test_property_connection_pool.py`

<!-- file: apps/m3u/tests/test_property_connection_pool.py -->
```python
"""Property tests for the shared-connection-pool counters (issue #145; seam #146).

Surfaces, with their line at seed a54b09a9, all in ``apps/m3u/connection_pool.py``:

- ``_safe_decr`` (``:232``)
- ``reserve_profile_slot`` (``:280``) and its credential half
  ``_reserve_server_group_slot_for_profile`` (``:261``)
- ``release_profile_slot`` (``:316``)

The Redis stand-in is in-module and implements only what these functions call.
The credential fingerprint is patched to a constant, so the tests need no
database. ``get_profile_credential_fingerprint`` reads ``Stream`` rows, and
it is a different surface.

The #146 seam: at seed ``_safe_decr`` returns early on ``current <= 0`` and
leaves a negative counter negative forever (the keys have no TTL). The
INCR-first reservation then admits streams past ``max_streams`` until the
counter climbs back. C-5 repairs the counter in both places.
"""

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u import connection_pool
from apps.m3u.connection_pool import (
    _safe_decr,
    profile_connections_key,
    release_profile_slot,
    reserve_profile_slot,
    server_group_connections_key,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

FINGERPRINT = "f" * 64
GROUP_ID = 7
CRED_KEY = server_group_connections_key(GROUP_ID, FINGERPRINT)


class FakeRedis:
    """In-memory stand-in for the five commands connection_pool uses."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        value = self.data.get(key)
        return None if value is None else str(value).encode()

    def set(self, key, value, ex=None):
        try:
            self.data[key] = int(value)
        except (TypeError, ValueError):
            self.data[key] = value

    def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def decr(self, key):
        self.data[key] = int(self.data.get(key, 0)) - 1
        return self.data[key]

    def delete(self, key):
        self.data.pop(key, None)

    def count(self, key):
        return int(self.data.get(key, 0))


def _profile(max_streams, pooled, profile_id=1):
    group = SimpleNamespace(id=GROUP_ID) if pooled else None
    return SimpleNamespace(
        id=profile_id, pk=profile_id, max_streams=max_streams,
        m3u_account=SimpleNamespace(server_group=group),
    )


def _fixed_fingerprint():
    return mock.patch.object(
        connection_pool, "get_profile_credential_fingerprint", return_value=FINGERPRINT
    )


class SafeDecrProperties(SimpleTestCase):
    @given(start=st.none() | st.integers(min_value=-10, max_value=20))
    @example(start=-1)  # #146: shrunk counterexample, left at -1.
    @example(start=-3)  # #146: the issue's drifted credential counter.
    def test_safe_decr_lands_on_one_less_but_never_below_zero(self, start):
        redis = FakeRedis({} if start is None else {"k": start})
        _safe_decr(redis, "k")
        self.assertEqual(redis.count("k"), max((start or 0) - 1, 0))


class ReserveProfileSlotProperties(SimpleTestCase):
    @given(max_streams=st.integers(min_value=1, max_value=6), extra=st.integers(min_value=1, max_value=4))
    def test_a_profile_admits_exactly_max_streams_then_refuses_as_profile_full(self, max_streams, extra):
        redis = FakeRedis()
        profile = _profile(max_streams, pooled=False)
        results = [reserve_profile_slot(profile, redis) for _ in range(max_streams + extra)]
        self.assertEqual([r[0] for r in results], [True] * max_streams + [False] * extra)
        self.assertEqual({r[2] for r in results[max_streams:]}, {"profile_full"})
        self.assertEqual(redis.count(profile_connections_key(profile.id)), max_streams)

    @given(attempts=st.integers(min_value=1, max_value=8), pooled=st.booleans())
    def test_an_unlimited_profile_always_reserves_and_counts_nothing(self, attempts, pooled):
        redis = FakeRedis({CRED_KEY: 3})
        with _fixed_fingerprint():
            for _ in range(attempts):
                self.assertEqual(reserve_profile_slot(_profile(0, pooled), redis), (True, 0, None))
        self.assertEqual(redis.data, {CRED_KEY: 3})

    @given(
        start=st.integers(min_value=-5, max_value=6),
        max_streams=st.integers(min_value=1, max_value=4),
        extra=st.integers(min_value=1, max_value=3),
    )
    @example(start=-3, max_streams=1, extra=3)  # #146: -3 admitted four streams against a cap of one.
    def test_the_credential_cap_holds_whatever_the_counter_drifted_to(self, start, max_streams, extra):
        redis = FakeRedis({CRED_KEY: start})
        admitted = 0
        with _fixed_fingerprint():
            for i in range(max_streams + extra):
                # A distinct profile per attempt, each with room of its own, so
                # only the shared credential counter can refuse.
                ok, _, reason = reserve_profile_slot(_profile(max_streams, True, profile_id=i + 1), redis)
                admitted += ok
                if not ok:
                    self.assertEqual(reason, "credential_full")
        self.assertEqual(admitted, max(0, max_streams - max(start, 0)))


class ReserveReleaseConservationProperties(SimpleTestCase):
    @given(
        start=st.integers(min_value=0, max_value=3),
        ops=st.lists(st.sampled_from(("reserve", "release")), max_size=12),
        profiles=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_counters_track_the_streams_held_one_stream_per_profile(self, start, ops, profiles, data):
        """Every release returns exactly what its reserve took, and nothing goes negative.

        The domain is restricted to one stream per profile at a time. At seed,
        ``_remember_credential_release_key`` (``connection_pool.py:241``) keeps
        ONE release key per profile id, and the first release deletes it
        (``:257``). A second stream on the same pooled profile therefore
        never returns its credential slot. That is a defect filed separately
        (plan I, finding F-4), not behaviour this test blesses. Widen ``held``
        to a multiset once it is fixed.
        """
        redis = FakeRedis({CRED_KEY: start})
        held = set()
        with _fixed_fingerprint():
            for op in ops:
                pid = data.draw(st.integers(min_value=1, max_value=profiles))
                if op == "reserve" and pid not in held:
                    ok, _, _ = reserve_profile_slot(_profile(10, True, profile_id=pid), redis)
                    self.assertTrue(ok)
                    held.add(pid)
                elif op == "release":
                    release_profile_slot(pid, redis)
                    held.discard(pid)
                for p in range(1, profiles + 1):
                    self.assertEqual(redis.count(profile_connections_key(p)), int(p in held))
                self.assertEqual(redis.count(CRED_KEY), start + len(held))
```

#### `apps/m3u/tests/test_property_db_retry.py`

<!-- file: apps/m3u/tests/test_property_db_retry.py -->
```python
"""Property tests for ``_db_query_with_retry`` (issue #69).

Surface at seed a54b09a9: ``apps/m3u/tasks.py:80``. A poisoned Celery DB
connection surfaces as a transient error. The helper retries up to
``max_retries`` attempts, resetting the connection between them, and
re-raises the last failure. A non-transient error propagates on the first
attempt, with no reset.

The connection reset is patched out, so no database is touched.
"""

from unittest import mock

from django.db import DatabaseError, InterfaceError, OperationalError
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u import tasks

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

transient = st.sampled_from((OperationalError, InterfaceError, IndexError, DatabaseError))
non_transient = st.sampled_from((ValueError, KeyError, RuntimeError, TypeError))


class _Flaky:
    """Raises ``errors`` in order, then returns ``value``."""

    def __init__(self, errors, value):
        self.errors = list(errors)
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)("boom")
        return self.value


class DbQueryWithRetryProperties(SimpleTestCase):
    @given(
        max_retries=st.integers(min_value=1, max_value=5),
        errors=st.lists(transient, max_size=6),
        value=st.integers() | st.text(max_size=5) | st.none(),
    )
    def test_transient_failures_are_retried_up_to_max_retries_with_a_reset_between(
        self, max_retries, errors, value
    ):
        fn = _Flaky(errors, value)
        with mock.patch.object(tasks, "_release_task_db_connection") as reset:
            if len(errors) >= max_retries:
                with self.assertRaises(errors[max_retries - 1]):
                    tasks._db_query_with_retry(fn, max_retries=max_retries)
                self.assertEqual(fn.calls, max_retries)
                self.assertEqual(reset.call_count, max_retries - 1)
            else:
                self.assertEqual(tasks._db_query_with_retry(fn, max_retries=max_retries), value)
                self.assertEqual(fn.calls, len(errors) + 1)
                self.assertEqual(reset.call_count, len(errors))

    @given(max_retries=st.integers(min_value=1, max_value=5), error=non_transient)
    def test_a_non_transient_error_propagates_at_once_without_a_reset(self, max_retries, error):
        fn = _Flaky([error], None)
        with mock.patch.object(tasks, "_release_task_db_connection") as reset:
            with self.assertRaises(error):
                tasks._db_query_with_retry(fn, max_retries=max_retries)
        self.assertEqual((fn.calls, reset.call_count), (1, 0))
```

#### `apps/m3u/tests/test_property_xc_account_values.py`

<!-- file: apps/m3u/tests/test_property_xc_account_values.py -->
```python
"""Property tests for provider-controlled Xtream account values (issue #200; seam #199).

Surfaces, with their line at seed a54b09a9:

- ``M3UAccountProfile._parse_exp_date`` (``apps/m3u/models.py:307``): a
  provider's ``user_info.exp_date`` (a unix timestamp or ISO string) becomes
  an aware datetime, or ``None`` for anything unparseable.
- ``M3UAccountProfile._parse_exp_date_from_custom_properties``
  (``apps/m3u/models.py:323``): reads ``custom_properties["user_info"]``.
- ``core.xtream_codes.normalize_server_url`` (``core/xtream_codes.py:9``):
  strips a pasted XC API endpoint (``.../player_api.php?...``) back to the
  server base URL.

The #199 seam: at seed ``datetime.fromtimestamp`` raises ``OverflowError`` for
a timestamp past the platform range, and the ``except`` does not catch it. A
non-dict ``user_info`` raises ``AttributeError``. ``save()`` re-parses on
every save, so one bad provider value wedges the row. C-3 catches
``OverflowError`` and reads ``user_info`` through a dict-or-``{}`` accessor.
After C-3 the parser is total over every JSON scalar, so this module draws
the full range with no overflow filter. #200's reference branch filtered the
overflow range out; that filter is gone here on purpose.
"""

import math
import string
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u.models import M3UAccountProfile
from core.xtream_codes import normalize_server_url

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

parse = M3UAccountProfile._parse_exp_date

# datetime's representable range: 0001-01-01 .. 9999-12-31T23:59:59 UTC.
MIN_EPOCH = -62135596800
MAX_EPOCH = 253402300799

json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(max_size=30)
    | st.integers().map(str)
    | st.floats().map(repr)
)
json_values = st.recursive(
    json_scalars,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=6,
)


class ParseExpDateProperties(SimpleTestCase):
    @given(value=json_values)
    # #199: past the platform time_t range these raised OverflowError.
    @example(value="999999999999999999999999")
    @example(value="1e30")
    @example(value=float("inf"))
    @example(value="-1e20")
    def test_exp_date_parsing_is_total_over_provider_json(self, value):
        result = parse(value)
        if result is not None:
            self.assertIsInstance(result, datetime)

    @given(
        value=st.integers(min_value=MIN_EPOCH, max_value=MAX_EPOCH)
        | st.floats(min_value=MIN_EPOCH, max_value=MAX_EPOCH, allow_nan=False)
    )
    def test_an_in_range_timestamp_is_that_instant_in_utc(self, value):
        expected = datetime(1970, 1, 1, tzinfo=timezone.utc).timestamp() + float(value)
        result = parse(value)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertAlmostEqual(result.timestamp(), expected, delta=1e-3)

    @given(value=st.integers(min_value=MIN_EPOCH, max_value=MAX_EPOCH))
    def test_a_digit_string_parses_like_its_number(self, value):
        self.assertEqual(parse(str(value)), parse(value))

    @given(user_info=json_values)
    # #199: a non-dict user_info raised AttributeError.
    @example(user_info=None)
    @example(user_info=[1])
    @example(user_info="x")
    @example(user_info={"exp_date": "999999999999999999999999"})
    def test_exp_date_from_custom_properties_is_total_over_any_user_info(self, user_info):
        profile = M3UAccountProfile(custom_properties={"user_info": user_info})
        result = profile._parse_exp_date_from_custom_properties()
        if result is not None:
            self.assertIsInstance(result, datetime)


hosts = st.from_regex(r"[a-z0-9][a-z0-9.-]{0,15}", fullmatch=True)
segments = st.text(alphabet=string.ascii_letters + string.digits + "_.~-", min_size=1, max_size=10).filter(
    lambda s: not s.endswith(".php") and s not in (".", "..")
)


class NormalizeServerUrlProperties(SimpleTestCase):
    @given(value=st.none() | st.text(max_size=120))
    def test_normalize_server_url_is_total_and_passes_falsy_through(self, value):
        result = normalize_server_url(value)
        if not value:
            self.assertIs(result, value)
        else:
            self.assertIsInstance(result, str)

    @given(
        scheme=st.sampled_from(("http", "https")),
        host=hosts,
        port=st.none() | st.integers(min_value=1, max_value=65535),
        base=st.lists(segments, max_size=3),
        endpoint=st.none() | st.sampled_from(("player_api.php", "get.php", "xmltv.php", "panel_api.php")),
        query=st.sampled_from(("", "?username=u&password=p", "?action=get_live_streams")),
        trailing_slash=st.booleans(),
    )
    def test_a_pasted_api_url_normalises_to_scheme_host_and_base_path(
        self, scheme, host, port, base, endpoint, query, trailing_slash
    ):
        netloc = f"{host}:{port}" if port else host
        base_path = "".join("/" + s for s in base)
        path = base_path + (f"/{endpoint}" if endpoint else "") + ("/" if trailing_slash and not endpoint else "")
        self.assertEqual(
            normalize_server_url(f"{scheme}://{netloc}{path}{query}"),
            f"{scheme}://{netloc}{base_path}",
        )

    @given(value=st.text(max_size=80).filter(lambda s: ";" not in s))
    def test_normalising_twice_changes_nothing(self, value):
        # ';' is excluded: urlparse splits ';params' off the LAST path segment
        # and the rebuild drops them, so 'http://h/a;b' loses ';b' and ';/'
        # takes two passes to settle (plan I, finding F-9).
        once = normalize_server_url(value)
        self.assertEqual(normalize_server_url(once), once)
```


### Appendix C: PR I-3, output and vod

#### `apps/output/tests/test_property_epg_export_helpers.py`

<!-- file: apps/output/tests/test_property_epg_export_helpers.py -->
```python
"""Property tests for the XMLTV export window helpers in ``apps/output/epg.py``.

Surfaces (``file:line`` at a54b09a9):

- ``_programme_overlaps_export_window`` (``apps/output/epg.py:34``): the filter every
  programme, real or dummy, passes through on its way into ``/output/epg``.
- ``_ceil_to_half_hour`` (``apps/output/epg.py:42``): where a custom dummy EPG starts
  filling the export window when its event lies outside it.
- ``generate_fallback_programs`` (``apps/output/epg.py:83``): the grid a custom dummy
  source emits when its title pattern does not match.

Closes the ``apps/output/epg.py`` half of #92 (dups #210, #162).
"""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.output.epg import (
    _ceil_to_half_hour,
    _programme_overlaps_export_window,
    generate_fallback_programs,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Instants within +/- 400 days of 2026-01-01, at one-second resolution, always
# UTC-aware: the export computes lookback and cutoff from django's timezone.now().
aware_instants = st.integers(-400 * 86400, 400 * 86400).map(
    lambda s: _EPOCH + timedelta(seconds=s)
)
# Microsecond-resolution naive and aware datetimes for the rounding helper.
any_datetimes = st.one_of(
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
    st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(timezone.utc),
    ),
)


class ProgrammeOverlapsExportWindowProperties(SimpleTestCase):
    """The programme is the closed interval [start, end]; the window is [lookback, cutoff)."""

    @given(
        start=aware_instants,
        length=st.integers(0, 3 * 86400),
        lookback=aware_instants,
        window=st.one_of(st.none(), st.integers(1, 30 * 86400)),
    )
    # A programme that ends exactly at the lookback boundary still overlaps (end >= lookback).
    @example(start=_EPOCH - timedelta(hours=1), length=3600, lookback=_EPOCH, window=None)
    # A programme that starts exactly at the cutoff does not (start < cutoff).
    @example(start=_EPOCH, length=3600, lookback=_EPOCH - timedelta(days=1), window=86400)
    def test_overlap_decision_is_closed_programme_against_half_open_window(
        self, start, length, lookback, window
    ):
        # The export builds a non-empty window: cutoff is now + num_days (or None when
        # num_days is 0) and lookback is now - prev_days (apps/output/epg.py:1192-1193).
        cutoff = None if window is None else lookback + timedelta(seconds=window)
        end = start + timedelta(seconds=length)
        # Oracle: some instant t with start <= t <= end and lookback <= t (< cutoff) exists.
        latest_admissible = end if cutoff is None else min(end, cutoff - timedelta(microseconds=1))
        earliest_admissible = max(start, lookback)
        expected = earliest_admissible <= latest_admissible
        self.assertEqual(
            _programme_overlaps_export_window(start, end, lookback, cutoff), expected
        )

    @given(
        lookback=aware_instants,
        span=st.integers(1, 30 * 86400),
        offset=st.floats(0, 1, exclude_max=True),
        length=st.floats(0, 1),
    )
    def test_programme_wholly_inside_the_window_always_overlaps(
        self, lookback, span, offset, length
    ):
        cutoff = lookback + timedelta(seconds=span)
        start = lookback + timedelta(seconds=int(span * offset))
        end = start + timedelta(seconds=int((cutoff - start).total_seconds() * length))
        self.assertTrue(_programme_overlaps_export_window(start, end, lookback, cutoff))
        self.assertTrue(_programme_overlaps_export_window(start, end, lookback, None))


class CeilToHalfHourProperties(SimpleTestCase):
    @given(dt=any_datetimes)
    @example(dt=datetime(2026, 1, 1, 10, 0, 0))  # already aligned: unchanged
    @example(dt=datetime(2026, 1, 1, 10, 0, 30))  # 30 s past :00 goes to :30, not :00
    @example(dt=datetime(2026, 1, 1, 10, 0, 0, 500))  # sub-second only: truncated, stays :00
    @example(dt=datetime(2026, 1, 1, 23, 59, 59))  # rolls over midnight
    def test_result_is_the_least_half_hour_boundary_not_before_the_second_truncated_input(
        self, dt
    ):
        result = _ceil_to_half_hour(dt)
        floor_second = dt.replace(microsecond=0)
        # Independent oracle: whole seconds since the input's own midnight, ceiled to 1800.
        midnight = floor_second.replace(hour=0, minute=0, second=0)
        secs = int((floor_second - midnight).total_seconds())
        expected = midnight + timedelta(seconds=-(-secs // 1800) * 1800)
        self.assertEqual(result, expected)
        self.assertEqual(result.tzinfo, dt.tzinfo)
        self.assertIn(result.minute, (0, 30))
        self.assertEqual((result.second, result.microsecond), (0, 0))

    @given(dt=any_datetimes)
    def test_ceil_is_idempotent(self, dt):
        once = _ceil_to_half_hour(dt)
        self.assertEqual(_ceil_to_half_hour(once), once)


class GenerateFallbackProgramsProperties(SimpleTestCase):
    @given(
        now=aware_instants,
        num_days=st.integers(0, 4),
        length=st.integers(1, 30),
        title=st.text(max_size=20),
        description=st.text(max_size=20),
        channel_name=st.text(min_size=1, max_size=20),
    )
    def test_grid_geometry_and_template_fallbacks(
        self, now, num_days, length, title, description, channel_name
    ):
        programs = generate_fallback_programs(
            7, channel_name, now, num_days, length, title, description
        )
        per_day = len(range(0, 24, length))  # hour offsets 0, length, ... < 24
        self.assertEqual(len(programs), num_days * per_day)
        for i, program in enumerate(programs):
            day, slot = divmod(i, per_day)
            expected_start = now + timedelta(days=day, hours=slot * length)
            self.assertEqual(program["start_time"], expected_start)
            self.assertEqual(program["end_time"] - program["start_time"], timedelta(hours=length))
            self.assertEqual(program["channel_id"], 7)
            self.assertEqual(program["title"], title or channel_name)
            self.assertEqual(
                program["description"],
                description or f"EPG information is currently unavailable for {channel_name}",
            )
```

#### `apps/output/tests/test_property_custom_dummy_programs.py`

<!-- file: apps/output/tests/test_property_custom_dummy_programs.py -->
```python
"""Property tests for ``generate_custom_dummy_programs`` (``apps/output/epg.py:258``).

A custom dummy EPG source runs operator-configured regexes over provider-controlled
channel names. Whatever a name makes those regexes capture, generation must return
programmes rather than raise: the export loop that calls it (``apps/output/epg.py:1652-1661``)
has no per-channel guard, so one raise truncates ``/output/epg`` for every client.

These properties hold after PR C-1 (#90, dup #211), which range-checks the captured
time and date. The counterexamples from those issues are pinned as ``@example`` rows.

Closes the custom-dummy half of #92 (dups #210, #162).
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.output.epg import generate_custom_dummy_programs

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# The documented dummy-EPG pattern shapes (#90's repro), widened with -? so a provider
# name can capture a negative value as well as an overlong one.
TIME_PATTERN = r"(?<hour>-?\d+):(?<minute>-?\d+)(?<ampm>am|pm|AM|PM)?"
DATE_PATTERN = r"(?<month>-?\d+)/(?<day>-?\d+)(?:/(?<year>-?\d+))?"
MONTH_ONLY_PATTERN = r"M(?<month>-?\d+)"

# `now` is passed in by the caller (hour-aligned UTC in generate_dummy_programs);
# drawn across two years so the 29th-31st of every month is reachable, which is
# what a month-only date pattern defaults its day from.
nows = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31, 23)
).map(lambda d: d.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc))

captured_ints = st.one_of(
    st.integers(-99, 199),
    st.integers(10**18, 10**22),  # overlong digit runs (#211's 20-digit minute)
)
years = st.one_of(st.integers(-5, 3000), st.sampled_from([0, 1, 9999, 10000, 99999]))
zones = st.sampled_from(["UTC", "US/Eastern", "Europe/London", "Asia/Kolkata"])


def _props(**extra):
    props = {"title_pattern": r"(?<title>.*)", "program_duration": 60}
    props.update(extra)
    return props


def _assert_well_formed(test, programs):
    test.assertIsInstance(programs, list)
    for program in programs:
        test.assertIsNotNone(program["start_time"].tzinfo)
        test.assertGreater(program["end_time"], program["start_time"])


class CustomDummyCaptureNeverRaises(SimpleTestCase):
    def setUp(self):
        # Every rejected capture logs a WARNING by design; 200 examples of them is noise.
        patcher = mock.patch("apps.output.epg.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(
        hour=captured_ints,
        minute=captured_ints,
        ampm=st.sampled_from(["", "am", "pm", "AM"]),
        date=st.one_of(st.none(), st.tuples(captured_ints, captured_ints, st.none() | years)),
        tz=zones,
        now=nows,
        num_days=st.integers(1, 3),
        window=st.booleans(),
    )
    # #90: minute 75 -> "ValueError: minute must be in 0..59" at seed.
    @example(hour=10, minute=75, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #90: hour -1.
    @example(hour=-1, minute=30, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #211: minute 99, and a 20-digit minute -> OverflowError at seed.
    @example(hour=10, minute=99, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=10, minute=99999999999999999999, ampm="", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # #90/#211: 2/31 -> "day is out of range for month".
    @example(hour=10, minute=30, ampm="", date=(2, 31, None), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # C-1: 13:30pm on the 12-hour arm -> hour 25.
    @example(hour=13, minute=30, ampm="pm", date=None, tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # C-1: year 0 and year 99999.
    @example(hour=10, minute=30, ampm="", date=(1, 2, 0), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=10, minute=30, ampm="", date=(1, 2, 99999), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    # Found by this property on C-1 as first planned (1 <= year <= 9999): the edge years
    # overflow after the range check, at the +program_duration (apps/output/epg.py:671)
    # and at pytz localize in a zone east of UTC (apps/output/epg.py:572).
    @example(hour=23, minute=30, ampm="", date=(12, 31, 9999), tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    @example(hour=0, minute=10, ampm="", date=(1, 1, 1), tz="Asia/Kolkata",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), num_days=1, window=False)
    def test_any_captured_time_or_date_yields_programmes_not_an_exception(
        self, hour, minute, ampm, date, tz, now, num_days, window
    ):
        name = f"Ch {hour}:{minute}{ampm}"
        extra = {"time_pattern": TIME_PATTERN, "timezone": tz}
        if date is not None:
            month, day, year = date
            name += f" {month}/{day}" + ("" if year is None else f"/{year}")
            extra["date_pattern"] = DATE_PATTERN
        # window=True is the /output/epg export call shape (apps/output/epg.py:1654-1661).
        lookback = now - timedelta(days=1) if window else None
        cutoff = now + timedelta(days=num_days) if window else None
        programs = generate_custom_dummy_programs(
            1, name, now, num_days, _props(**extra),
            export_lookback=lookback, export_cutoff=cutoff,
        )
        _assert_well_formed(self, programs)

    @given(hour=st.integers(0, 23), minute=st.integers(0, 59),
           month=captured_ints, now=nows)
    # C-1 (found reading apps/output/epg.py:476,504): a month-only pattern defaults the
    # day to now.day, so on the 31st a month of 30 days or fewer raised.
    @example(hour=10, minute=30, month=2, now=datetime(2026, 1, 31, 12, tzinfo=timezone.utc))
    @example(hour=10, minute=30, month=4, now=datetime(2026, 3, 31, 12, tzinfo=timezone.utc))
    def test_month_only_capture_never_builds_an_impossible_date(self, hour, minute, month, now):
        programs = generate_custom_dummy_programs(
            1, f"Ch {hour}:{minute:02d} M{month}", now, 1,
            _props(time_pattern=TIME_PATTERN, date_pattern=MONTH_ONLY_PATTERN),
        )
        _assert_well_formed(self, programs)


class TwelveHourCaptureMatchesTwentyFourHour(SimpleTestCase):
    """#210: the 12h -> 24h conversion places the event at the same instant as the
    equivalent 24-hour capture, by comparing two code paths of the function."""

    def setUp(self):
        patcher = mock.patch("apps.output.epg.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(hour12=st.integers(1, 12), minute=st.integers(0, 59),
           ampm=st.sampled_from(["am", "pm"]), tz=zones, now=nows,
           days_ahead=st.integers(0, 5))
    @example(hour12=12, minute=0, ampm="am", tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), days_ahead=1)  # midnight
    @example(hour12=12, minute=0, ampm="pm", tz="UTC",
             now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc), days_ahead=1)  # noon
    def test_same_programme_times(self, hour12, minute, ampm, tz, now, days_ahead):
        # Independent 12h -> 24h table, not the function's own branch.
        hour24 = {("am", 12): 0, ("pm", 12): 12}.get((ampm, hour12), hour12 + (12 if ampm == "pm" else 0))
        d = (now + timedelta(days=days_ahead)).date()
        date_text = f"{d.month}/{d.day}/{d.year}"
        props = _props(time_pattern=TIME_PATTERN, date_pattern=DATE_PATTERN, timezone=tz)
        as12 = generate_custom_dummy_programs(1, f"X {hour12}:{minute:02d}{ampm} {date_text}", now, 1, props)
        as24 = generate_custom_dummy_programs(1, f"X {hour24}:{minute:02d} {date_text}", now, 1, props)
        self.assertEqual(
            [(p["start_time"], p["end_time"]) for p in as12],
            [(p["start_time"], p["end_time"]) for p in as24],
        )
        self.assertTrue(as12)
```

#### `apps/output/tests/test_property_output_formatting.py`

<!-- file: apps/output/tests/test_property_output_formatting.py -->
```python
"""Property tests for the pure formatting and normalisation helpers behind the output APIs.

Surfaces (``file:line`` at a54b09a9):

- ``format_duration_hms`` (``apps/output/views.py:1778``): renders a provider's
  ``duration_secs`` into XC ``get_series_info`` (``apps/output/views.py:1494``).
- ``_encode_chunk`` / ``_decode_chunk`` (``apps/output/streaming_chunk_cache.py:44``, ``:36``):
  the leader stores encoded chunks and followers replay decoded ones, so a follower's
  M3U/XMLTV body must equal the leader's.
- ``format_channel_number`` (``apps/channels/utils.py:46``): the channel number in the
  M3U, the XMLTV and the HDHomeRun lineup.
- ``coerce_channel_profile_ids`` (``apps/channels/utils.py:22``): group-settings
  ``custom_properties`` in and out of the API.
- ``custom_properties_as_dict`` / ``ensure_custom_properties_dict`` (``core/utils.py:79``,
  ``:105``): the normaliser every ``custom_properties`` reader goes through.

Closes the formatting half of #92 (dups #210, #162).
"""

import json
import math
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.channels.utils import coerce_channel_profile_ids, format_channel_number
from apps.output.streaming_chunk_cache import _decode_chunk, _encode_chunk
from apps.output.views import format_duration_hms
from core.utils import custom_properties_as_dict, ensure_custom_properties_dict

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Values a JSONField can hold. Floats are finite: PostgreSQL jsonb rejects NaN and
# Infinity, and DRF's JSON parser refuses the NaN/Infinity tokens. One gap: json.loads
# reads the literal 1e999 as inf, and coerce_channel_profile_ids then raises
# OverflowError (plan I finding F-8), so finite floats are also that finding's exclusion.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(10**6), 10**6)
    | st.floats(allow_nan=False, allow_infinity=False, width=32) | st.text(max_size=10),
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=6), children, max_size=4),
    max_leaves=12,
)
json_dicts = st.dictionaries(st.text(max_size=6), json_values, max_size=4)


class FormatDurationHmsProperties(SimpleTestCase):
    @given(seconds=st.integers(0, 10**7))
    @example(seconds=0)
    @example(seconds=59)
    @example(seconds=3600)
    @example(seconds=360000)  # 100 hours: the hour field widens past two digits
    def test_renders_zero_padded_fields_that_sum_back_to_the_input(self, seconds):
        text = format_duration_hms(seconds)
        hh, mm, ss = text.split(":")
        self.assertGreaterEqual(len(hh), 2)
        self.assertEqual((len(mm), len(ss)), (2, 2))
        self.assertTrue(0 <= int(mm) < 60 and 0 <= int(ss) < 60)
        self.assertEqual(int(hh) * 3600 + int(mm) * 60 + int(ss), seconds)

    @given(seconds=st.floats(0, 10**7, allow_nan=False))
    def test_float_input_renders_as_its_truncated_whole_seconds(self, seconds):
        self.assertEqual(format_duration_hms(seconds), format_duration_hms(int(seconds)))

    @given(falsy=st.sampled_from([None, 0, 0.0, "", False]))
    def test_falsy_input_is_zero(self, falsy):
        self.assertEqual(format_duration_hms(falsy), "00:00:00")


class ChunkCacheCodecProperties(SimpleTestCase):
    # st.text() excludes surrogates by default; chunks are built from text PostgreSQL
    # stored, and PostgreSQL cannot store a lone surrogate.
    @given(chunk=st.text(max_size=200))
    @example(chunk="<tv>é\U0001f4fa</tv>\n")
    def test_text_chunk_round_trips_exactly(self, chunk):
        encoded = _encode_chunk(chunk)
        self.assertIsInstance(encoded, bytes)
        self.assertEqual(_decode_chunk(encoded), chunk)

    @given(chunk=st.binary(max_size=200))
    def test_bytes_chunk_is_stored_as_given(self, chunk):
        self.assertIs(_encode_chunk(chunk), chunk)

    @given(chunk=st.text(max_size=50))
    def test_decode_passes_text_and_none_through(self, chunk):
        self.assertIs(_decode_chunk(chunk), chunk)
        self.assertIsNone(_decode_chunk(None))


class FormatChannelNumberProperties(SimpleTestCase):
    # Finite values only. format_channel_number(nan) raises ValueError and inf raises
    # OverflowError; plan I finding F-7 traces how a provider can probably store either.
    @given(whole=st.integers(-(10**9), 10**9))
    def test_whole_valued_float_renders_as_int(self, whole):
        result = format_channel_number(float(whole))
        self.assertIs(type(result), int)
        self.assertEqual(result, whole)

    @given(value=st.floats(-(10**9), 10**9, allow_nan=False).filter(lambda f: f != int(f)))
    @example(value=12.5)
    def test_fractional_float_is_returned_unchanged(self, value):
        self.assertEqual(format_channel_number(value), value)

    @given(sentinel=st.sampled_from(["", None, "-", 0]))
    def test_none_returns_the_caller_sentinel(self, sentinel):
        self.assertIs(format_channel_number(None, empty=sentinel), sentinel)


class CoerceChannelProfileIdsProperties(SimpleTestCase):
    def setUp(self):
        # custom_properties_as_dict warns on every non-JSON string; not the subject here.
        patcher = mock.patch("core.utils.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(value=json_values)
    def test_any_json_value_returns_a_dict_with_int_ids(self, value):
        result = coerce_channel_profile_ids(value)
        self.assertIsInstance(result, dict)
        if "channel_profile_ids" in result:
            self.assertTrue(all(type(i) is int for i in result["channel_profile_ids"]))

    @given(props=json_dicts, ids=st.lists(json_values, max_size=5))
    @example(props={}, ids=["3", 4, "x", None, 2.0])  # the UI MultiSelect sends strings
    def test_ids_are_the_int_convertible_items_in_order(self, props, ids):
        props = dict(props, channel_profile_ids=ids)
        expected = []
        for item in ids:  # independent oracle: exactly what int() accepts
            try:
                expected.append(int(item))
            except (TypeError, ValueError):
                pass
        result = coerce_channel_profile_ids(props)
        self.assertEqual(result["channel_profile_ids"], expected)
        self.assertEqual(
            {k: v for k, v in result.items() if k != "channel_profile_ids"},
            {k: v for k, v in props.items() if k != "channel_profile_ids"},
        )

    @given(props=json_dicts)
    def test_input_dict_is_not_mutated(self, props):
        props = dict(props, channel_profile_ids=["1", 2, "x"])
        snapshot = json.dumps(props, sort_keys=True)
        coerce_channel_profile_ids(props)
        self.assertEqual(json.dumps(props, sort_keys=True), snapshot)

    @given(props=json_dicts)
    def test_json_encoded_string_row_coerces_like_the_dict(self, props):
        props = dict(props, channel_profile_ids=["7", 8])
        self.assertEqual(
            coerce_channel_profile_ids(json.dumps(props)), coerce_channel_profile_ids(props)
        )


class CustomPropertiesDictProperties(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("core.utils.logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    @given(value=json_values)
    def test_always_returns_a_dict(self, value):
        self.assertIsInstance(custom_properties_as_dict(value), dict)
        self.assertIsInstance(ensure_custom_properties_dict(value), dict)

    @given(value=json_dicts)
    def test_dict_passes_through_by_identity(self, value):
        self.assertIs(custom_properties_as_dict(value), value)
        self.assertIs(ensure_custom_properties_dict(value), value)

    @given(value=json_dicts)
    def test_json_encoded_dict_string_decodes_to_that_dict(self, value):
        self.assertEqual(custom_properties_as_dict(json.dumps(value)), value)

    @given(value=json_values.filter(lambda v: not isinstance(v, dict)))
    def test_json_encoded_non_dict_string_is_empty(self, value):
        self.assertEqual(custom_properties_as_dict(json.dumps(value)), {})

    @given(value=st.text(max_size=30))
    @example(value="{not json")
    def test_ensure_agrees_with_as_dict_for_strings(self, value):
        self.assertEqual(ensure_custom_properties_dict(value), custom_properties_as_dict(value))
```

#### `apps/vod/tests/test_property_image_proxy.py`

<!-- file: apps/vod/tests/test_property_image_proxy.py -->
```python
"""Property-based tests for the VOD image proxy's pure helpers.

Surfaces (``file:line`` at a54b09a9):

- ``is_proxyable_image_url`` (``apps/vod/image_proxy.py:22``): the allowlist that decides
  which stored, provider-controlled URL strings the image proxy will fetch. Security
  relevant, so the exact allowlist is pinned: a ``str`` starting with ``http://``,
  ``https://`` or ``/data``, case-sensitive, nothing else.
- ``_as_backdrop_list`` (``:29``): normalises every stored ``backdrop_path`` shape to a list.
- ``get_relation_artwork`` (``:39``): walks ``info`` > ``info.info`` > ``detailed_info`` >
  ``basic_data`` > the top level, in that order, and always returns
  ``{"movie_image": str, "backdrop_path": list}``.
- ``prefer_relation_artwork`` (``:88``): relation artwork wins, the object's is the fallback.
- ``_url_from_props`` (``:136``): backdrop index bounds, and nothing unproxyable escapes.
- ``format_vod_image_url`` (``:199``) and ``rewrite_backdrop_paths`` (``:220``): the proxy
  URL layout, and a 1:1 rewrite that XC clients index into.

Issues: #92 (vod half), #210, #162.
"""

import hashlib
import string
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.vod.image_proxy import (
    _as_backdrop_list,
    _url_from_props,
    format_vod_image_url,
    get_relation_artwork,
    is_proxyable_image_url,
    prefer_relation_artwork,
    rewrite_backdrop_paths,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# The allowlist, written out independently of the helper under test.
_ALLOWED_PREFIXES = ("http://", "https://", "/data")

# Anything a JSONField (or a buggy caller) can hand these helpers.
anything = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**12), max_value=10**12)
    | st.floats(allow_nan=True, allow_infinity=True)
    | st.text(max_size=40)
    | st.binary(max_size=20),
    lambda children: st.lists(children, max_size=5)
    | st.tuples(children, children)
    | st.dictionaries(st.text(max_size=12), children, max_size=5),
    max_leaves=20,
)

# URL-ish text that lands on both sides of the allowlist often, not only by accident.
url_like = st.one_of(
    st.tuples(
        st.sampled_from(
            _ALLOWED_PREFIXES
            + ("HTTP://", "Https://", " http://", "ftp://", "file://", "//", "data:", "/dat", "javascript:", "")
        ),
        st.text(max_size=30),
    ).map("".join),
    st.text(max_size=60),
)

# A non-blank artwork URL and the three blank-ish values providers send instead.
artwork_url = st.text(string.ascii_letters + string.digits + "/:.-_", min_size=1, max_size=20).map(
    lambda s: "https://img/" + s
)
blankish = st.sampled_from([None, "", "   "])
_IMAGE_KEYS = ("movie_image", "cover_big", "stream_icon", "cover")


class IsProxyableImageUrlProperties(SimpleTestCase):
    @given(value=st.one_of(anything, url_like))
    @example(value="HTTP://host/a.jpg")  # scheme match is case-sensitive: rejected
    @example(value=" http://host/a.jpg")  # leading whitespace: rejected
    @example(value="file:///etc/passwd")
    @example(value="//evil/a.jpg")  # scheme-relative: rejected
    @example(value="data:image/png;base64,AAAA")
    @example(value="javascript:alert(1)")
    @example(value="/dat")
    @example(value=b"http://host/a.jpg")  # bytes are not str: rejected
    def test_is_proxyable_image_url_is_exactly_the_three_prefix_allowlist(self, value):
        expected = isinstance(value, str) and value.startswith(_ALLOWED_PREFIXES)
        self.assertIs(is_proxyable_image_url(value), expected)


class AsBackdropListProperties(SimpleTestCase):
    @given(value=anything)
    def test_as_backdrop_list_always_returns_a_list_of_the_input_shape(self, value):
        result = _as_backdrop_list(value)
        self.assertIsInstance(result, list)
        if not value:
            self.assertEqual(result, [])
        elif isinstance(value, str):
            self.assertEqual(result, [value])
        elif isinstance(value, (list, tuple)):
            self.assertEqual(result, list(value))
        else:
            self.assertEqual(result, [])


def _layers_to_props(info, nested, detailed, basic, top):
    props = dict(top)
    if info is not None:
        info = dict(info)
        if nested is not None:
            info["info"] = nested
        props["info"] = info
    if detailed is not None:
        props["detailed_info"] = detailed
    if basic is not None:
        props["basic_data"] = basic
    return props


# One layer: absent (None), or a dict carrying at most one image key and at most one backdrop.
layer = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {},
        optional={
            "img": st.tuples(st.sampled_from(_IMAGE_KEYS), st.one_of(artwork_url, blankish)),
            "backdrop_path": st.one_of(artwork_url, st.lists(artwork_url, max_size=3), blankish),
        },
    ).map(lambda d: ({d["img"][0]: d["img"][1]} if "img" in d else {}) | (
        {"backdrop_path": d["backdrop_path"]} if "backdrop_path" in d else {}
    )),
)


class RelationArtworkProperties(SimpleTestCase):
    @given(props=anything)
    def test_get_relation_artwork_shape_is_stable_for_any_stored_value(self, props):
        art = get_relation_artwork(props)
        self.assertEqual(set(art), {"movie_image", "backdrop_path"})
        self.assertIsInstance(art["movie_image"], str)
        self.assertEqual(art["movie_image"], art["movie_image"].strip())
        self.assertIsInstance(art["backdrop_path"], list)

    @given(info=layer, nested=layer, detailed=layer, basic=layer, top=layer.map(lambda d: d or {}))
    def test_get_relation_artwork_takes_the_first_layer_that_has_a_value(
        self, info, nested, detailed, basic, top
    ):
        props = _layers_to_props(info, nested, detailed, basic, top)
        # Precedence order, written out from the docstring rather than read from the code.
        ordered = [
            l
            for l in (info, nested if info is not None else None, detailed, basic, top)
            if l is not None
        ]
        expected_image = ""
        for l in ordered:
            values = [l[k] for k in _IMAGE_KEYS if k in l]
            if values and isinstance(values[0], str) and values[0].strip():
                expected_image = values[0].strip()
                break
        expected_backdrop = []
        for l in ordered:
            bp = l.get("backdrop_path")
            if isinstance(bp, str) and bp:
                expected_backdrop = [bp]
                break
            if isinstance(bp, list) and bp:
                expected_backdrop = bp
                break
        art = get_relation_artwork(props)
        self.assertEqual(art["movie_image"], expected_image)
        self.assertEqual(art["backdrop_path"], expected_backdrop)

    @given(rel=anything, obj=anything)
    def test_prefer_relation_artwork_shape_is_stable(self, rel, obj):
        art = prefer_relation_artwork(rel, obj)
        self.assertEqual(set(art), {"movie_image", "backdrop_path"})
        self.assertIsInstance(art["movie_image"], str)
        self.assertIsInstance(art["backdrop_path"], list)

    @given(
        rel_image=st.one_of(artwork_url, blankish),
        obj_image=st.one_of(artwork_url, blankish, st.integers(), st.lists(artwork_url, max_size=2)),
        rel_bp=st.one_of(st.lists(artwork_url, max_size=2), blankish),
        obj_bp=st.one_of(st.lists(artwork_url, max_size=2), artwork_url, blankish),
    )
    def test_prefer_relation_artwork_relation_wins_and_object_fills_gaps(
        self, rel_image, obj_image, rel_bp, obj_bp
    ):
        art = prefer_relation_artwork(
            {"movie_image": rel_image, "backdrop_path": rel_bp},
            {"movie_image": obj_image, "backdrop_path": obj_bp},
        )
        if isinstance(rel_image, str) and rel_image.strip():
            self.assertEqual(art["movie_image"], rel_image.strip())
        elif isinstance(obj_image, str):
            self.assertEqual(art["movie_image"], obj_image.strip())
        else:
            self.assertEqual(art["movie_image"], "")
        # A non-empty string is one backdrop; a non-empty list is the backdrops.
        def as_list(v):
            return [v] if isinstance(v, str) and v else list(v) if isinstance(v, list) else []

        self.assertEqual(art["backdrop_path"], as_list(rel_bp) or as_list(obj_bp))


class UrlFromPropsProperties(SimpleTestCase):
    # ``index`` reaches _url_from_props only as the ``?index=`` query string
    # (apps/vod/image_proxy.py:318), so strings (and the int default) are the whole domain.
    @given(
        paths=st.lists(url_like, max_size=6),
        index=st.one_of(st.integers(min_value=-10, max_value=10), st.text(max_size=8)),
    )
    @example(paths=["http://a/0.jpg", "http://a/1.jpg"], index="-1")  # negative index: no wraparound
    @example(paths=["http://a/0.jpg"], index="1")  # one past the end
    @example(paths=["file:///etc/passwd"], index="0")  # in range but unproxyable
    def test_url_from_props_backdrop_index_is_bounds_checked(self, paths, index):
        result = _url_from_props({"backdrop_path": paths}, "backdrop", index)
        try:
            idx = int(index)
        except ValueError:
            self.assertIsNone(result)
            return
        if 0 <= idx < len(paths) and isinstance(paths[idx], str) and paths[idx].startswith(_ALLOWED_PREFIXES):
            self.assertEqual(result, paths[idx])
        else:
            self.assertIsNone(result)

    @given(kind=st.sampled_from(["movie_image", "poster_path"]), value=st.one_of(anything, url_like))
    def test_url_from_props_never_returns_an_unproxyable_url(self, kind, value):
        result = _url_from_props({kind: value}, kind)
        if result is not None:
            self.assertIs(result, value)
            self.assertTrue(result.startswith(_ALLOWED_PREFIXES))
        else:
            self.assertFalse(isinstance(value, str) and value.startswith(_ALLOWED_PREFIXES))


class ProxyUrlLayoutProperties(SimpleTestCase):
    @given(
        pk=st.integers(min_value=0, max_value=10**9),
        kind=st.sampled_from(["backdrop", "movie_image", "poster_path"]),
        index=st.integers(min_value=0, max_value=50),
        source_url=st.one_of(st.none(), st.just(""), url_like),
        account=st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
    )
    def test_format_vod_image_url_layout(self, pk, kind, index, source_url, account):
        url = format_vod_image_url(
            "/api/vod/movies/", "/image/", pk, kind, index=index, source_url=source_url, m3u_account_id=account
        )
        parts = urlsplit(url)
        self.assertEqual(parts.path, f"/api/vod/movies/{pk}/image/")
        query = parse_qs(parts.query, keep_blank_values=True)
        self.assertEqual(query.pop("kind"), [kind])
        if kind == "backdrop":
            self.assertEqual(query.pop("index"), [str(index)])
        if account is not None:
            self.assertEqual(query.pop("m3u_account_id"), [str(account)])
        if source_url:
            self.assertEqual(query.pop("v"), [hashlib.md5(source_url.encode()).hexdigest()[:8]])
        self.assertEqual(query, {})

    @given(
        backdrop_path=st.one_of(anything, url_like, st.lists(st.one_of(url_like, anything), max_size=5)),
        account=st.one_of(st.none(), st.integers(min_value=0, max_value=99)),
    )
    @example(backdrop_path=["http://a/0.jpg", "rel/1.jpg", "https://a/2.jpg"], account=None)
    def test_rewrite_backdrop_paths_is_one_to_one_and_rewrites_only_proxyable_entries(
        self, backdrop_path, account
    ):
        parts = ("/pre/", "/suf")
        result = rewrite_backdrop_paths(None, "movie", 7, backdrop_path, url_parts=parts, m3u_account_id=account)
        if not backdrop_path or not isinstance(backdrop_path, (str, list, tuple)):
            self.assertEqual(result, [])
            return
        entries = [backdrop_path] if isinstance(backdrop_path, str) else list(backdrop_path)
        self.assertEqual(len(result), len(entries))
        for i, (before, after) in enumerate(zip(entries, result)):
            if isinstance(before, str) and before.startswith(_ALLOWED_PREFIXES):
                self.assertEqual(
                    after,
                    format_vod_image_url(*parts, 7, "backdrop", index=i, source_url=before, m3u_account_id=account),
                )
                self.assertIn(f"&index={i}", after)
            else:
                self.assertIs(after, before)
```

#### `apps/vod/tests/test_property_provider_helpers.py`

<!-- file: apps/vod/tests/test_property_provider_helpers.py -->
```python
"""Property-based tests for the VOD provider-data normalisation helpers.

``apps/vod/tasks.py`` feeds these helpers fields from arbitrary IPTV provider JSON during
movie and series refresh. JSON has no schema, and XC panels are inconsistent about types:
a year may arrive as ``2011`` rather than ``"2011"``. So the properties draw provider values
from every JSON shape unless a comment says why a narrower domain is the real one.

Surfaces (``file:line`` at a54b09a9):

- ``extract_duration_from_data`` (``:1165``), ``normalize_rating`` (``:1193``),
  ``extract_year`` (``:1220``), ``extract_year_from_title`` (``:1230``) and ``parse_date``
  (``:1307``);
- ``is_non_empty_string`` (``:2106``), ``extract_string_from_array_or_string`` (``:2114``),
  ``clean_custom_properties`` (``:2132``), ``should_update_field`` (``:2163``) and
  ``is_blank_vod_value`` (``:2177``).

Issues: #243, and #92 (``parse_date``). ``extract_year``'s JSON-wide domain is the widening
#242 asked for once its fix (plan C, PR C-6) landed.
"""

import math
import string
from datetime import date, datetime

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.vod.tasks import (
    clean_custom_properties,
    extract_duration_from_data,
    extract_string_from_array_or_string,
    extract_year,
    extract_year_from_title,
    is_blank_vod_value,
    is_non_empty_string,
    normalize_rating,
    parse_date,
    should_update_field,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Any value json.loads can produce. Integers are bounded because json.loads itself refuses an
# int over sys.get_int_max_str_digits() digits, so a larger one never reaches these helpers.
json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=30),
)
jsonish = st.recursive(
    json_scalar,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=12), children, max_size=5),
    ),
    max_leaves=10,
)


def _has_text(value):
    """A provider value 'carries text': a non-blank string, or a list with an item whose text
    form is non-blank. Written out from the docstrings, independently of the helpers."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(item is not None and str(item).strip() for item in value)
    return False


class ExtractDurationProperties(SimpleTestCase):
    # Plan I finding F-6 (not filed at a54b09a9): a non-integer ``duration_secs`` ("1.5", "abc", a list,
    # inf, nan) raises at apps/vod/tasks.py:1171, and a ``duration`` made of isdigit()-but-not-decimal
    # characters ("²") raises at :1176, both outside any try. The per-movie try at :434/:545 drops
    # that one movie. Until that is fixed, the never-raises domain below is integer
    # ``duration_secs`` and ``duration`` text without Unicode category No (where "²" lives).
    @given(
        secs=st.one_of(st.none(), st.integers(min_value=-(10**12), max_value=10**12),
                       st.integers(min_value=0, max_value=10**12).map(str)),
        duration=st.one_of(
            st.none(),
            st.integers(min_value=0, max_value=10**6),
            st.text(st.characters(exclude_categories=("No", "Cs")), max_size=12),
            st.text("0123456789:-", max_size=10),
        ),
    )
    def test_extract_duration_never_raises_on_integer_seconds_or_duration_text(self, secs, duration):
        row = {k: v for k, v in (("duration_secs", secs), ("duration", duration)) if v is not None}
        result = extract_duration_from_data(row)
        self.assertTrue(result is None or (isinstance(result, int) and not isinstance(result, bool)))

    @given(secs=st.integers(min_value=1, max_value=10**9), duration=st.text(max_size=12))
    def test_extract_duration_prefers_a_non_zero_duration_secs(self, secs, duration):
        self.assertEqual(extract_duration_from_data({"duration_secs": secs, "duration": duration}), secs)
        self.assertEqual(extract_duration_from_data({"duration_secs": str(secs)}), secs)

    @given(minutes=st.integers(min_value=1, max_value=10**4))
    def test_extract_duration_zero_seconds_falls_through_to_duration(self, minutes):
        # duration_secs is a truthiness check: 0 means "absent", so ``duration`` decides.
        self.assertEqual(
            extract_duration_from_data({"duration_secs": 0, "duration": str(minutes)}), minutes * 60
        )

    @given(h=st.integers(0, 99), m=st.integers(0, 59), s=st.integers(0, 59), pad=st.booleans())
    def test_extract_duration_hms_and_ms_parse_to_seconds(self, h, m, s, pad):
        fmt = "{:02d}" if pad else "{}"
        hms = ":".join(fmt.format(v) for v in (h, m, s))
        ms = ":".join(fmt.format(v) for v in (m, s))
        self.assertEqual(extract_duration_from_data({"duration": hms}), h * 3600 + m * 60 + s)
        self.assertEqual(extract_duration_from_data({"duration": ms}), m * 60 + s)

    @given(minutes=st.integers(min_value=0, max_value=10**6), as_int=st.booleans())
    def test_extract_duration_bare_number_means_minutes(self, minutes, as_int):
        value = minutes if as_int else str(minutes)
        result = extract_duration_from_data({"duration": value})
        if value == 0:
            self.assertIsNone(result)  # an int 0 is falsy: there is no duration at all
        else:
            self.assertEqual(result, minutes * 60)  # "0" is truthy text and yields 0


class NormalizeRatingProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_normalize_rating_never_raises_and_returns_none_or_a_float_string(self, value):
        result = normalize_rating(value)
        if result is not None:
            self.assertIsInstance(result, str)
            float(result)
        if not value:
            self.assertIsNone(result)

    @given(value=st.floats(allow_nan=False, allow_infinity=False).filter(lambda v: v != 0.0),
           as_text=st.booleans())
    def test_normalize_rating_round_trips_non_zero_finite_floats_exactly(self, value, as_text):
        result = normalize_rating(repr(value) if as_text else value)
        self.assertEqual(float(result), value)

    @given(whole=st.integers(0, 10), frac=st.integers(0, 999))
    def test_normalize_rating_reads_a_decimal_comma(self, whole, frac):
        self.assertEqual(normalize_rating(f" {whole},{frac} "), str(float(f"{whole}.{frac}")))


class ExtractYearProperties(SimpleTestCase):
    @given(value=jsonish)
    # #242: a truthy non-string provider value raised AttributeError from date_string.split.
    @example(value=1)  # #242's shrunk counterexample
    @example(value=2011)  # "releaseDate": 2011, as XC panels send it
    @example(value=[2011])
    @example(value=2011.5)
    @example(value=True)
    def test_extract_year_never_raises_on_any_json_value(self, value):
        result = extract_year(value)
        self.assertTrue(result is None or (isinstance(result, int) and not isinstance(result, bool)))

    # From 1: an int 0 is falsy and short-circuits to None, while the text "0" yields 0. That
    # asymmetry is the helper's own ``if not date_string`` guard and predates #242.
    @given(year=st.integers(min_value=1, max_value=10**6))
    @example(year=1)  # #242
    @example(year=2011)  # #242
    def test_extract_year_reads_an_integer_year_like_its_string_form(self, year):
        self.assertEqual(extract_year(year), year)
        self.assertEqual(extract_year(year), extract_year(str(year)))

    def test_extract_year_c6_expected_values(self):
        # Plan C, PR C-6's table: the int year is kept, other non-string shapes yield no year.
        for value, expected in ((1, 1), (2011, 2011), ([2011], None), (2011.5, None), (True, None)):
            with self.subTest(value=value):
                self.assertEqual(extract_year(value), expected)

    @given(year=st.integers(1, 9999), month=st.integers(1, 12), day=st.integers(1, 28), tail=st.text(max_size=8))
    def test_extract_year_takes_the_year_of_an_iso_date(self, year, month, day, tail):
        self.assertEqual(extract_year(f"{year:04d}-{month:02d}-{day:02d}{tail}"), year)


class ExtractYearFromTitleProperties(SimpleTestCase):
    @given(title=st.one_of(st.none(), st.text(max_size=80)))
    def test_extract_year_from_title_never_raises_and_stays_in_the_window(self, title):
        result = extract_year_from_title(title)
        self.assertTrue(result is None or 1900 <= result <= 2030)

    @given(
        name=st.text(string.ascii_letters + " ", min_size=1, max_size=20).filter(lambda s: s.strip()),
        year=st.integers(1900, 2030),
        form=st.sampled_from(["{n} ({y})", "{n} - {y}", "{n} {y}"]),
    )
    def test_extract_year_from_title_finds_each_documented_form(self, name, year, form):
        self.assertEqual(extract_year_from_title(form.format(n=name.strip(), y=year)), year)

    @given(year=st.one_of(st.integers(1000, 1899), st.integers(2031, 9999)),
           form=st.sampled_from(["Film ({y})", "Film - {y}", "Film {y}"]))
    def test_extract_year_from_title_rejects_years_outside_1900_to_2030(self, year, form):
        self.assertIsNone(extract_year_from_title(form.format(y=year)))


class ParseDateProperties(SimpleTestCase):
    # Domain is ``str``: the only caller, extract_date_from_data (:1292), passes a value only
    # after isinstance(date_value, str), inside a broad try.
    @given(value=st.one_of(st.text(max_size=40), st.text("0123456789-/:TZ. +", max_size=30)))
    def test_parse_date_never_raises_on_text(self, value):
        result = parse_date(value)
        self.assertTrue(result is None or isinstance(result, datetime))

    @given(d=st.dates())
    def test_parse_date_parses_every_canonical_date(self, d):
        self.assertEqual(parse_date(d.isoformat()), datetime(d.year, d.month, d.day))

    @given(dt=st.datetimes())
    def test_parse_date_round_trips_isoformat(self, dt):
        self.assertEqual(parse_date(dt.isoformat()), dt)

    @given(year=st.integers(1, 9999), month=st.integers(1, 12), day=st.integers(29, 31))
    def test_parse_date_returns_none_for_an_impossible_calendar_date(self, year, month, day):
        try:
            date(year, month, day)
        except ValueError:
            self.assertIsNone(parse_date(f"{year:04d}-{month:02d}-{day:02d}"))


class StringFieldProperties(SimpleTestCase):
    @given(value=jsonish)
    def test_is_non_empty_string_truthiness_is_non_blank_str(self, value):
        self.assertEqual(bool(is_non_empty_string(value)), isinstance(value, str) and bool(value.strip()))

    @given(value=jsonish)
    @example(value=[None, "  ", 0])  # the 0 is text "0": non-blank
    @example(value=[{"a": 1}])
    def test_extract_string_is_the_first_item_with_text_stripped(self, value):
        result = extract_string_from_array_or_string(value)
        if isinstance(value, str):
            expected = value.strip() or None
        elif isinstance(value, list):
            expected = next(
                (str(i).strip() for i in value if i is not None and str(i).strip()), None
            )
        else:
            expected = None
        self.assertEqual(result, expected)

    @given(existing=jsonish, new=jsonish)
    @example(existing="kept", new="new")
    @example(existing=None, new="   ")
    @example(existing=[None, ""], new=["x"])
    def test_should_update_field_iff_new_has_text_and_existing_has_none(self, existing, new):
        self.assertIs(should_update_field(existing, new), _has_text(new) and not _has_text(existing))

    @given(value=jsonish)
    @example(value=())  # a tuple is not a list: not blank
    @example(value=[None, ""])
    @example(value=0)
    def test_is_blank_vod_value_is_none_empty_or_a_list_of_only_blanks(self, value):
        expected = value is None or (isinstance(value, str) and value == "") or (
            isinstance(value, list) and all(i is None or (isinstance(i, str) and i == "") for i in value)
        )
        self.assertIs(is_blank_vod_value(value), expected)


_STRING_FIELDS = ("youtube_trailer", "actors", "director", "cast")


class CleanCustomPropertiesProperties(SimpleTestCase):
    # Domain is a dict or a falsy value: every caller passes a provider row or ``info`` already
    # normalised to a dict (apps/vod/tasks.py:2233-2240, :2334, :2358-2359).
    @given(
        props=st.one_of(
            st.none(),
            st.dictionaries(
                st.one_of(st.sampled_from(_STRING_FIELDS + ("backdrop_path", "genre", "rating")),
                          st.text(max_size=8)),
                jsonish,
                max_size=8,
            ),
        )
    )
    @example(props={"actors": ["", None, " Ann "], "backdrop_path": [None, " http://x/b.jpg "]})
    @example(props={"a": None, "b": "", "c": [], "d": [None, None]})
    def test_clean_custom_properties_keeps_only_meaningful_values(self, props):
        result = clean_custom_properties(props)
        if result is None:
            result = {}
        else:
            self.assertTrue(result)  # an empty cleaning is None, never {}
        for key, value in (props or {}).items():
            if key in _STRING_FIELDS:
                if _has_text(value):
                    self.assertEqual(result[key], extract_string_from_array_or_string(value))
                    self.assertEqual(result[key], result[key].strip())
                else:
                    self.assertNotIn(key, result)
            elif key == "backdrop_path":
                if _has_text(value):
                    self.assertEqual(result[key], [extract_string_from_array_or_string(value)])
                else:
                    self.assertNotIn(key, result)
            elif value is None or value == "" or value == [] or (
                isinstance(value, list) and all(i is None for i in value)
            ):
                self.assertNotIn(key, result)
            else:
                self.assertIs(result[key], value)
        self.assertLessEqual(set(result), set(props or {}))
```


### Appendix D: PR I-4, timeshift

#### `apps/timeshift/tests/test_property_timestamps.py`

<!-- file: apps/timeshift/tests/test_property_timestamps.py -->
```python
"""Property tests for the catch-up timestamp, duration and stream-ordering helpers.

Surfaces (``file:line`` at a54b09a9):

- ``normalize_catchup_timestamp_input`` (apps/timeshift/helpers.py:46) and
  ``parse_catchup_timestamp`` (:98): client-controlled text (XC PATH/QUERY
  ``start``, native API ``start``). The documented contract is "an ISO string /
  naive datetime, or None" -- never an exception, because ``_serve_catchup``
  (apps/timeshift/views.py:341) and the native API (apps/timeshift/api_views.py:127)
  turn ``None`` into a 400.
- ``format_timestamp_as_*`` (helpers.py:501-518): unparseable input passes through.
- ``convert_timestamp_to_provider_tz`` (helpers.py:134): identity for a falsy/UTC or
  unknown zone; otherwise the same instant in the provider zone, keeping the
  requested seconds (#111, PR D-3).
- ``client_duration_to_window`` (helpers.py:197) and ``resolve_catchup_duration``
  (helpers.py:224).
- ``programme_age_days`` (helpers.py:521) and ``order_catchup_streams_for_timestamp``
  (helpers.py:542).

Closes the timestamp/duration/ordering scope of #192 (survivor), #260 and #55.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    DEFAULT_DURATION_MINUTES,
    DURATION_BUFFER_MINUTES,
    MAX_DURATION_MINUTES,
    client_duration_to_window,
    convert_timestamp_to_provider_tz,
    format_timestamp_as_colon_dash,
    format_timestamp_as_colon_seconds,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
    normalize_catchup_timestamp_input,
    order_catchup_streams_for_timestamp,
    parse_catchup_timestamp,
    programme_age_days,
    resolve_catchup_duration,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

ISO_SHAPE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"

# Plan I finding F-5 (not filed at a54b09a9): normalize_catchup_timestamp_input raises instead
# of returning None on two input shapes. (1) An isdigit()-but-not-decimal run such as
# "111111111\u00b2": "\u00b2" is Unicode category No, isdigit() is true and int() refuses it
# (helpers.py:70). (2) An ISO timestamp whose offset pushes year 1 or 9999 out of range, such as
# "0001-01-01T00:00+01:00" (OverflowError past the ValueError-only except at helpers.py:80-87).
# Both shapes are excluded from the arbitrary-text domain on purpose, so that no test passes
# only because the derandomized draw happened to miss them. Once F-5 is fixed, drop both
# exclusions and add those two inputs as @examples on
# test_normalize_returns_iso_shape_or_none_for_arbitrary_text.
_F5_EDGE_YEAR = re.compile(r"^\s*(0001|9999)-")
timestamp_text = (
    st.text(st.characters(exclude_categories=("No", "Cs")), max_size=64)
    | st.text(alphabet="0123456789-_:TZ.+ ", min_size=1, max_size=40)
).filter(lambda s: not _F5_EDGE_YEAR.match(s))

# Wall-clock instants. Years are kept inside 1900..2100 for the same finding (F-5): at the
# calendar's edges the ISO-offset branch and the provider-zone conversion raise
# OverflowError at seed. Every real catch-up start is well inside.
instants = st.datetimes(
    min_value=datetime(1900, 1, 1), max_value=datetime(2100, 12, 31, 23, 59, 59)
)

wall_clock_inputs = st.builds(
    lambda d, dtsep, hmsep, with_s: (
        d,
        f"{d:%Y-%m-%d}{dtsep}{d:%H}{hmsep}{d:%M}"
        + (f"{hmsep}{d:%S}" if with_s else ""),
        with_s,
    ),
    instants.map(lambda d: d.replace(microsecond=0)),
    st.sampled_from([":", "_", " "]),
    st.sampled_from(["-", ":"]),
    st.booleans(),
)

PROVIDER_ZONES = [
    "Europe/Brussels", "Europe/London", "America/New_York", "America/Los_Angeles",
    "Asia/Kolkata", "Asia/Kathmandu", "Australia/Lord_Howe", "Pacific/Chatham",
    "America/St_Johns", "Asia/Tokyo",
]


class TimestampParserProperties(SimpleTestCase):
    @given(value=timestamp_text)
    def test_normalize_returns_iso_shape_or_none_for_arbitrary_text(self, value):
        result = normalize_catchup_timestamp_input(value)
        if result is not None:
            self.assertRegex(result, ISO_SHAPE)

    @given(value=timestamp_text)
    def test_parse_agrees_with_normalize_and_is_naive(self, value):
        iso = normalize_catchup_timestamp_input(value)
        parsed = parse_catchup_timestamp(value)
        if iso is None:
            self.assertIsNone(parsed)
        else:
            self.assertIsNone(parsed.tzinfo)
            self.assertEqual(parsed.isoformat(timespec="seconds"), iso)

    @given(value=timestamp_text)
    def test_normalize_is_idempotent(self, value):
        once = normalize_catchup_timestamp_input(value)
        if once is not None:
            self.assertEqual(normalize_catchup_timestamp_input(once), once)

    @given(case=wall_clock_inputs)
    def test_every_documented_wall_clock_shape_parses_to_its_own_fields(self, case):
        dt, text, with_seconds = case
        expected = dt if with_seconds else dt.replace(second=0)
        self.assertEqual(parse_catchup_timestamp(text), expected)

    @given(
        dt=instants.map(lambda d: d.replace(microsecond=0)),
        offset_minutes=st.integers(min_value=-14 * 60, max_value=14 * 60),
        zulu=st.booleans(),
    )
    def test_iso_with_offset_normalizes_to_the_same_utc_instant(
        self, dt, offset_minutes, zulu,
    ):
        if zulu:
            text = dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            expected = dt
        else:
            tz = timezone(timedelta(minutes=offset_minutes))
            text = dt.replace(tzinfo=tz).isoformat()
            expected = dt - timedelta(minutes=offset_minutes)
        self.assertEqual(parse_catchup_timestamp(text), expected)

    @given(value=st.integers(min_value=1_000_000_000, max_value=9_999_999_999))
    def test_ten_digit_epoch_is_utc_seconds(self, value):
        expected = datetime(1970, 1, 1) + timedelta(seconds=value)
        self.assertEqual(parse_catchup_timestamp(str(value)), expected)

    @given(value=st.integers(min_value=1_000_000_000_000, max_value=9_999_999_999_999))
    def test_thirteen_digit_epoch_is_utc_milliseconds_truncated_to_the_second(self, value):
        expected = datetime(1970, 1, 1) + timedelta(seconds=value // 1000)
        self.assertEqual(parse_catchup_timestamp(str(value)), expected)

    @given(
        digits=st.text(alphabet="0123456789", min_size=1, max_size=20).filter(
            lambda s: len(s) not in (10, 13)
        )
    )
    def test_any_other_ascii_digit_run_is_rejected(self, digits):
        self.assertIsNone(normalize_catchup_timestamp_input(digits))


class TimestampReshapeProperties(SimpleTestCase):
    FORMATTERS = (
        (format_timestamp_as_colon_dash, "%Y-%m-%d:%H-%M"),
        (format_timestamp_as_colon_seconds, "%Y-%m-%d:%H:%M:%S"),
        (format_timestamp_as_underscore, "%Y-%m-%d_%H-%M"),
        (format_timestamp_as_sql_datetime, "%Y-%m-%d %H:%M:%S"),
    )

    @given(value=timestamp_text)
    def test_unparseable_input_passes_through_every_formatter_unchanged(self, value):
        if parse_catchup_timestamp(value) is not None:
            return
        # Each formatter logs one ERROR naming the rejected value (helpers.py:127-129).
        with self.assertLogs("apps.timeshift.helpers", level="ERROR") as logs:
            for formatter, _ in self.FORMATTERS:
                self.assertEqual(formatter(value), value)
        self.assertEqual(len(logs.records), len(self.FORMATTERS))

    @given(case=wall_clock_inputs)
    def test_parseable_input_is_reshaped_to_the_documented_layout(self, case):
        _, text, _ = case
        parsed = parse_catchup_timestamp(text)
        for formatter, fmt in self.FORMATTERS:
            self.assertEqual(formatter(text), parsed.strftime(fmt))


class ProviderTimezoneProperties(SimpleTestCase):
    @given(value=timestamp_text, zone=st.sampled_from([None, "", "UTC"]))
    def test_falsy_or_utc_zone_is_the_identity(self, value, zone):
        self.assertEqual(convert_timestamp_to_provider_tz(value, zone), value)

    @given(
        dt=instants.map(lambda d: d.replace(microsecond=0)),
        zone=st.text(alphabet="abcXYZ/_.-+0123456789 \x00", min_size=1, max_size=24),
    )
    def test_unknown_zone_returns_the_input_unchanged(self, dt, zone):
        if zone in PROVIDER_ZONES or zone == "UTC":
            return
        try:
            ZoneInfo(zone)
        except Exception:
            text = dt.strftime("%Y-%m-%d:%H-%M")
            with self.assertLogs("apps.timeshift.helpers", level="WARNING"):
                self.assertEqual(convert_timestamp_to_provider_tz(text, zone), text)

    @given(
        dt=instants.map(lambda d: d.replace(microsecond=0)),
        zone=st.sampled_from(PROVIDER_ZONES),
    )
    # #111: a non-UTC zone dropped the requested seconds (12:00:45 UTC -> 13-00 in
    # Brussels) while the UTC branch kept them. D-3 keeps them.
    @example(dt=datetime(2026, 1, 15, 12, 0, 45), zone="Europe/Brussels")
    def test_provider_zone_conversion_is_the_same_instant_and_keeps_requested_seconds(
        self, dt, zone,
    ):
        text = dt.strftime("%Y-%m-%d:%H-%M") + (f"-{dt:%S}" if dt.second else "")
        local = dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zone))
        expected = local.strftime(
            "%Y-%m-%d:%H-%M-%S" if local.second else "%Y-%m-%d:%H-%M"
        )
        self.assertEqual(convert_timestamp_to_provider_tz(text, zone), expected)


class DurationWindowProperties(SimpleTestCase):
    @given(hint=st.integers(min_value=-10_000, max_value=10_000), as_text=st.booleans(),
           pad=st.sampled_from(["", " ", "\t", "  \n"]))
    def test_integer_hint_is_buffered_and_capped_or_rejected(self, hint, as_text, pad):
        value = f"{pad}{hint}{pad}" if as_text else hint
        expected = (
            min(hint + DURATION_BUFFER_MINUTES, MAX_DURATION_MINUTES) if hint > 0 else None
        )
        self.assertEqual(client_duration_to_window(value), expected)

    @given(value=st.none() | st.text(max_size=20) | st.floats(allow_nan=True)
           | st.lists(st.integers(), max_size=2))
    def test_any_hint_yields_none_or_a_window_within_bounds(self, value):
        window = client_duration_to_window(value)
        if window is not None:
            self.assertIsInstance(window, int)
            self.assertGreaterEqual(window, 1 + DURATION_BUFFER_MINUTES)
            self.assertLessEqual(window, MAX_DURATION_MINUTES)

    @given(hint=st.none() | st.integers(min_value=-500, max_value=5000)
           | st.text(max_size=8), timestamp=timestamp_text)
    def test_resolve_prefers_a_usable_hint_and_otherwise_falls_back_without_epg(
        self, hint, timestamp,
    ):
        channel = SimpleNamespace(epg_data=None)
        window = client_duration_to_window(hint)
        result = resolve_catchup_duration(channel, timestamp, client_hint=hint)
        self.assertEqual(result, window if window is not None else DEFAULT_DURATION_MINUTES)
        self.assertGreaterEqual(result, 1)
        self.assertLessEqual(result, MAX_DURATION_MINUTES)


# A stream as order_catchup_streams_for_timestamp sees it: only catchup_days matters.
catchup_days_values = st.none() | st.integers(min_value=-3, max_value=30) | st.sampled_from(
    ["7", "0", "", "abc", "3.5", " 14 "]
)
streams_strategy = st.lists(
    catchup_days_values.map(lambda d: SimpleNamespace(catchup_days=d)), max_size=8
)


def _days(stream):
    raw = stream.catchup_days
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


class ProgrammeAgeAndOrderingProperties(SimpleTestCase):
    @given(
        now=instants.map(lambda d: d.replace(microsecond=0)),
        delta_secs=st.integers(min_value=-5 * 86400, max_value=60 * 86400),
        aware_now=st.booleans(),
    )
    def test_age_is_zero_for_future_starts_and_the_whole_day_ceiling_otherwise(
        self, now, delta_secs, aware_now,
    ):
        start = now - timedelta(seconds=delta_secs)
        text = start.strftime("%Y-%m-%d %H:%M:%S")
        passed_now = now.replace(tzinfo=timezone.utc) if aware_now else now
        expected = 0 if delta_secs <= 0 else max(1, math.ceil(delta_secs / 86400))
        self.assertEqual(programme_age_days(text, now=passed_now), expected)

    @given(value=timestamp_text)
    def test_age_is_none_exactly_when_the_timestamp_is_unparseable(self, value):
        age = programme_age_days(value, now=datetime(2026, 1, 1))
        self.assertEqual(age is None, parse_catchup_timestamp(value) is None)

    @given(
        streams=streams_strategy,
        age_days=st.integers(min_value=0, max_value=40),
    )
    def test_ordering_is_a_stable_partition_preferred_then_fallback(self, streams, age_days):
        now = datetime(2026, 6, 1, 12, 0, 0)
        start = now - timedelta(days=age_days)
        ordered = order_catchup_streams_for_timestamp(
            streams, start.strftime("%Y-%m-%d %H:%M:%S"), now=now,
        )
        age = programme_age_days(start.strftime("%Y-%m-%d %H:%M:%S"), now=now)
        preferred = [s for s in streams if _days(s) <= 0 or _days(s) >= age]
        fallback = [s for s in streams if not (_days(s) <= 0 or _days(s) >= age)]
        self.assertEqual([id(s) for s in ordered], [id(s) for s in preferred + fallback])

    @given(streams=streams_strategy, value=timestamp_text)
    def test_unparseable_timestamp_leaves_the_order_unchanged_in_a_new_list(self, streams, value):
        if parse_catchup_timestamp(value) is not None:
            return
        ordered = order_catchup_streams_for_timestamp(streams, value)
        self.assertEqual([id(s) for s in ordered], [id(s) for s in streams])
        self.assertIsNot(ordered, streams)
```

#### `apps/timeshift/tests/test_property_url_builders.py`

<!-- file: apps/timeshift/tests/test_property_url_builders.py -->
```python
"""Property tests for the provider catch-up URL builders.

Surfaces (``file:line`` at a54b09a9), all in apps/timeshift/helpers.py:

- ``build_timeshift_url_format_a`` (:412, QUERY layout) and
  ``build_timeshift_url_format_b`` (:424, PATH layout): the reserved profile's
  credentials are percent-encoded with ``quote(..., safe='')``, so a password
  containing ``&``, ``=``, ``/``, ``?`` or ``#`` cannot add a query parameter or a
  path segment to the provider URL.
- ``client_timeshift_url_layout`` (:436) and ``build_timeshift_redirect_url`` (:449).
- ``build_timeshift_candidate_urls`` (:466): seven candidates, every PATH form
  before every QUERY form.

Closes the URL-builder scope of #192 (survivor), #260 and #55.
"""

from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    build_timeshift_redirect_url,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    client_timeshift_url_layout,
    parse_catchup_timestamp,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Credentials a hostile or careless provider account could carry, weighted toward
# URL-structural characters.
credential = st.text(max_size=24) | st.text(alphabet="&=/?#%+ ;:@a1", max_size=12)
server_url = st.builds(
    lambda host, port, slashes: f"http://{host}{port}{'/' * slashes}",
    st.from_regex(r"[a-z][a-z0-9.-]{0,20}", fullmatch=True),
    st.sampled_from(["", ":8080", ":80"]),
    st.integers(min_value=0, max_value=3),
)
creds_strategy = st.builds(TimeshiftCredentials, server_url, credential, credential)
stream_ids = st.integers(min_value=1, max_value=10**9)
durations = st.integers(min_value=1, max_value=480)
provider_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31)
).map(lambda d: d.strftime("%Y-%m-%d:%H-%M"))


def _path_segments_after_host(url):
    return urlsplit(url).path.split("/")[1:]


class ProviderUrlLayoutProperties(SimpleTestCase):
    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_query_layout_carries_exactly_the_five_params_with_credentials_intact(
        self, creds, stream_id, ts, dur,
    ):
        url = build_timeshift_url_format_a(creds, stream_id, ts, dur)
        parts = urlsplit(url)
        self.assertEqual(parts.path.rsplit("/", 2)[-2:], ["streaming", "timeshift.php"])
        self.assertEqual(parts.fragment, "")
        params = parse_qs(parts.query, keep_blank_values=True, strict_parsing=False)
        self.assertEqual(
            params,
            {
                "username": [creds.username],
                "password": [creds.password],
                "stream": [str(stream_id)],
                "start": [ts],
                "duration": [str(dur)],
            },
        )

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_path_layout_is_exactly_six_segments_with_credentials_intact(
        self, creds, stream_id, ts, dur,
    ):
        url = build_timeshift_url_format_b(creds, stream_id, ts, dur)
        self.assertEqual(urlsplit(url).fragment, "")
        self.assertEqual(urlsplit(url).query, "")
        segments = _path_segments_after_host(url)
        self.assertEqual(len(segments), 6, url)
        self.assertEqual(segments[0], "timeshift")
        self.assertEqual(unquote(segments[1]), creds.username)
        self.assertEqual(unquote(segments[2]), creds.password)
        self.assertEqual(segments[3:], [str(dur), ts, f"{stream_id}.ts"])

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_trailing_slashes_on_server_url_never_double_the_separator(
        self, creds, stream_id, ts, dur,
    ):
        host = creds.server_url.rstrip("/")
        for url in (
            build_timeshift_url_format_a(creds, stream_id, ts, dur),
            build_timeshift_url_format_b(creds, stream_id, ts, dur),
        ):
            self.assertTrue(url.startswith(host + "/"))
            self.assertFalse(url[len(host):].startswith("//"))

    @given(path=st.text(max_size=40), inject=st.booleans(),
           spelling=st.sampled_from(["timeshift.php", "TIMESHIFT.PHP", "TimeShift.Php"]))
    def test_layout_is_query_exactly_when_the_path_names_timeshift_php(
        self, path, inject, spelling,
    ):
        if inject:
            path = f"/streaming/{spelling}{path}"
        request = SimpleNamespace(path=path)
        expected = "query" if "timeshift.php" in path.lower() else "path"
        self.assertEqual(client_timeshift_url_layout(request), expected)

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps,
           dur=durations, layout=st.sampled_from(["query", "path", "", None, "other"]))
    def test_redirect_url_mirrors_the_client_layout(self, creds, stream_id, ts, dur, layout):
        url = build_timeshift_redirect_url(creds, stream_id, ts, dur, layout)
        if layout == "query":
            self.assertEqual(url, build_timeshift_url_format_a(creds, stream_id, ts, dur))
        else:
            self.assertEqual(url, build_timeshift_url_format_b(creds, stream_id, ts, dur))


class CandidateUrlProperties(SimpleTestCase):
    @given(creds=creds_strategy, stream_id=stream_ids,
           ts=provider_timestamps | st.text(max_size=30), dur=durations)
    def test_seven_candidates_every_path_form_before_every_query_form(
        self, creds, stream_id, ts, dur,
    ):
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        self.assertEqual(len(urls), 7)
        kinds = [
            "query" if urlsplit(u).path.endswith("/streaming/timeshift.php") else "path"
            for u in urls
        ]
        self.assertEqual(kinds, ["path"] * 3 + ["query"] * 4)

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_parseable_timestamp_is_offered_in_the_four_documented_shapes(
        self, creds, stream_id, ts, dur,
    ):
        dt = parse_catchup_timestamp(ts)
        colon_dash = dt.strftime("%Y-%m-%d:%H-%M")
        underscore = dt.strftime("%Y-%m-%d_%H-%M")
        colon_seconds = dt.strftime("%Y-%m-%d:%H:%M:%S")
        sql = dt.strftime("%Y-%m-%d %H:%M:%S")
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        path_starts = [_path_segments_after_host(u)[4] for u in urls[:3]]
        query_starts = [parse_qs(urlsplit(u).query)["start"][0] for u in urls[3:]]
        self.assertEqual(path_starts, [colon_dash, underscore, colon_seconds])
        self.assertEqual(query_starts, [underscore, sql, colon_dash, colon_seconds])

    @given(creds=creds_strategy, stream_id=stream_ids,
           ts=st.text(alphabet="abcxyz!~-_", min_size=1, max_size=20), dur=durations)
    def test_unparseable_timestamp_is_passed_through_verbatim_to_every_candidate(
        self, creds, stream_id, ts, dur,
    ):
        if parse_catchup_timestamp(ts) is not None:
            return
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        self.assertEqual([_path_segments_after_host(u)[4] for u in urls[:3]], [ts] * 3)
        self.assertEqual([parse_qs(urlsplit(u).query)["start"][0] for u in urls[3:]], [ts] * 4)
```

#### `apps/timeshift/tests/test_property_ranges.py`

<!-- file: apps/timeshift/tests/test_property_ranges.py -->
```python
"""Property tests for the catch-up HTTP Range / Content-Range helpers.

Written against the contracts PR D-3 (#141, #216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9; D-3 moves them by a few lines), all in
apps/timeshift/views.py unless named:

- ``_parse_client_range`` (:1111) and ``_parse_range_start`` (:1103): RFC 9110
  ``bytes=a-`` / ``bytes=a-b`` only. The suffix form ``bytes=-N`` and an inverted
  ``b < a`` are None (#141). ``_is_suffix_range`` is new in D-3.
- ``_parse_content_range_header`` (:1131): ``bytes a-b/T`` with ``a <= b`` and
  ``b < T`` (or ``T == '*'``), else None (#141).
- ``_extract_representation_length`` (:1151) and ``_build_downstream_length_headers``
  (:1169): never a negative Content-Length, and never an unsatisfiable Content-Range
  (#141).
- ``_is_near_eof_probe`` (:1230) and ``is_near_eof_offset`` (apps/timeshift/stats.py,
  new in D-3): an archive no larger than the probe window has no tail (#216), and a
  suffix range is a tail probe by definition (#141).
- ``_cap_open_ended_range`` (:1353) and ``_is_full_restart_range`` (:1303).
- ``_map_client_range_through_presentation`` (:1946) and
  ``_presentation_relative_content_range`` (:1961): translation by the presentation
  byte base, and never the absolute CDN range beside a presentation length (#141).

Every parser consumes remote input: the client's ``Range`` header and the provider's
``Content-Range``, both Latin-1 text under WSGI and requests. Hence the ``²``
examples: ``'²'.isdigit()`` is True but ``int('²')`` raises.

Closes the Range scope of #192 (survivor), #142, #215 and #260.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.timeshift import stats as ts_stats
from apps.timeshift import views as ts_views

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_stats.EOF_PROBE_TAIL_BYTES
UNKNOWN_LENGTH_MIN = ts_views._EOF_PROBE_UNKNOWN_LENGTH_MIN

offsets = st.integers(min_value=0, max_value=10**12)
# Header text a client or provider could send: arbitrary Latin-1 text, and the
# structural alphabet with the digit look-alikes that break isdigit()-based parsing.
header_text = (
    st.text(alphabet=st.characters(max_codepoint=0xFF), max_size=40)
    | st.text(alphabet="0123456789-/*, =bytes²³¹\t", max_size=30)
)
client_range_text = header_text | header_text.map(lambda s: "bytes=" + s)
content_range_text = header_text | header_text.map(lambda s: "bytes " + s)


def _satisfiable_client_range(parsed):
    start, end = parsed
    return isinstance(start, int) and start >= 0 and (end is None or end >= start)


class ClientRangeParserProperties(SimpleTestCase):
    @given(header=st.none() | client_range_text)
    # #141: a suffix and an inverted range were both returned as (start, end) pairs.
    @example(header="bytes=-500")
    @example(header="bytes=100-50")
    # isdigit() accepts Latin-1 superscripts that int() refuses (plan I, D-3 seam).
    @example(header="bytes=²-")
    @example(header="bytes=0-²")
    @example(header="bytes=--5")
    def test_parse_client_range_is_none_or_a_satisfiable_pair_for_any_header(self, header):
        parsed = ts_views._parse_client_range(header)
        if parsed is not None:
            self.assertTrue(_satisfiable_client_range(parsed), (header, parsed))
            self.assertEqual(ts_views._parse_range_start(header), parsed[0])
        else:
            self.assertIsNone(ts_views._parse_range_start(header))

    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9))
    def test_well_formed_range_specs_round_trip(self, start, length):
        if length is None:
            header, expected = f"bytes={start}-", (start, None)
        else:
            header, expected = f"bytes={start}-{start + length}", (start, start + length)
        self.assertEqual(ts_views._parse_client_range(header), expected)

    @given(n=st.integers(min_value=1, max_value=10**9))
    @example(n=500)  # #141's counterexample
    def test_suffix_range_is_not_parsed_as_a_prefix(self, n):
        header = f"bytes=-{n}"
        self.assertIsNone(ts_views._parse_client_range(header))
        self.assertTrue(ts_views._is_suffix_range(header))

    @given(end=offsets, gap=st.integers(min_value=1, max_value=10**6))
    @example(end=50, gap=50)  # #141: bytes=100-50
    def test_inverted_range_is_rejected(self, end, gap):
        self.assertIsNone(ts_views._parse_client_range(f"bytes={end + gap}-{end}"))

    @given(header=st.none() | client_range_text)
    @example(header="bytes=-²")
    @example(header="bytes=-0")
    def test_is_suffix_range_holds_exactly_for_bytes_dash_positive_ascii_n(self, header):
        tail = header[len("bytes=-"):] if header and header.startswith("bytes=-") else None
        expected = (
            tail is not None and tail.isascii() and tail.isdigit() and int(tail) > 0
        )
        self.assertEqual(ts_views._is_suffix_range(header), expected)


class ContentRangeParserProperties(SimpleTestCase):
    @given(value=st.none() | content_range_text)
    # #141: an inverted upstream Content-Range was accepted and later produced
    # Content-Length: -49.
    @example(value="bytes 100-50/1000")
    @example(value="bytes 0-10/10")
    @example(value="bytes ²-5/10")
    @example(value="bytes 0-5/²")
    def test_content_range_is_none_or_a_satisfiable_range(self, value):
        parsed = ts_views._parse_content_range_header(value)
        if parsed is None:
            return
        self.assertLessEqual(0, parsed["start"])
        self.assertLessEqual(parsed["start"], parsed["end"])
        if parsed["total"] is not None:
            self.assertLess(parsed["end"], parsed["total"])

    @given(start=offsets, length=st.integers(min_value=1, max_value=10**9),
           slack=st.none() | st.integers(min_value=0, max_value=10**9))
    def test_well_formed_content_range_round_trips(self, start, length, slack):
        end = start + length - 1
        total = None if slack is None else end + 1 + slack
        value = f"bytes {start}-{end}/{'*' if total is None else total}"
        self.assertEqual(
            ts_views._parse_content_range_header(value),
            {"start": start, "end": end, "total": total},
        )

    @given(content_range=st.none() | content_range_text,
           content_length=st.none() | st.text(max_size=12)
           | st.integers(min_value=0, max_value=10**12).map(str))
    def test_representation_length_prefers_the_content_range_total(
        self, content_range, content_length,
    ):
        headers = {}
        if content_range is not None:
            headers["Content-Range"] = content_range
        if content_length is not None:
            headers["Content-Length"] = content_length
        response = SimpleNamespace(headers=headers)
        result = ts_views._extract_representation_length(response)
        parsed = ts_views._parse_content_range_header(content_range or "")
        if parsed and parsed["total"] is not None:
            self.assertEqual(result, parsed["total"])
        elif content_length:
            try:
                expected = int(content_length)
            except ValueError:
                expected = None
            self.assertEqual(result, expected)
        else:
            self.assertIsNone(result)
        self.assertIsNone(ts_views._extract_representation_length(None))


class DownstreamHeaderProperties(SimpleTestCase):
    @given(
        range_header=st.none() | client_range_text,
        status_code=st.sampled_from([200, 206]),
        representation_length=st.none() | st.integers(min_value=0, max_value=10**10),
        upstream_content_range=st.none() | content_range_text,
        upstream_content_length=st.none() | st.integers(min_value=1, max_value=10**10),
        streaming=st.booleans(),
    )
    # #141: an inverted client range, a start past EOF, and an inverted upstream range.
    @example(range_header="bytes=100-50", status_code=206, representation_length=100,
             upstream_content_range=None, upstream_content_length=None, streaming=True)
    @example(range_header="bytes=5000-", status_code=206, representation_length=100,
             upstream_content_range=None, upstream_content_length=None, streaming=True)
    @example(range_header="bytes=0-", status_code=206, representation_length=None,
             upstream_content_range="bytes 100-50/1000", upstream_content_length=None,
             streaming=True)
    def test_headers_never_carry_an_unsatisfiable_range_or_a_negative_length(
        self, range_header, status_code, representation_length,
        upstream_content_range, upstream_content_length, streaming,
    ):
        headers = ts_views._build_downstream_length_headers(
            range_header=range_header,
            status_code=status_code,
            representation_length=representation_length,
            upstream_content_range=upstream_content_range,
            upstream_content_length=upstream_content_length,
            streaming=streaming,
        )
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        if "Content-Length" in headers:
            self.assertGreaterEqual(int(headers["Content-Length"]), 0, headers)
        if "Content-Range" in headers:
            self.assertIsNotNone(
                ts_views._parse_content_range_header(headers["Content-Range"]), headers
            )

    @given(total=st.integers(min_value=1, max_value=10**10),
           upstream_content_length=st.none() | st.integers(min_value=1, max_value=10**10))
    def test_plain_streaming_200_advertises_the_representation_length(
        self, total, upstream_content_length,
    ):
        headers = ts_views._build_downstream_length_headers(
            range_header=None, status_code=200, representation_length=total,
            upstream_content_range=None, upstream_content_length=upstream_content_length,
            streaming=True,
        )
        self.assertEqual(headers["Content-Length"], str(total))

    @given(start=st.integers(min_value=0, max_value=10**9),
           span=st.none() | st.integers(min_value=0, max_value=10**9),
           total=st.integers(min_value=1, max_value=10**10))
    def test_synthesised_206_content_range_is_clamped_inside_the_representation(
        self, start, span, total,
    ):
        header = f"bytes={start}-" if span is None else f"bytes={start}-{start + span}"
        headers = ts_views._build_downstream_length_headers(
            range_header=header, status_code=206, representation_length=total,
            upstream_content_range=None, upstream_content_length=None, streaming=True,
        )
        last = total - 1 if span is None else min(start + span, total - 1)
        if start <= last:
            self.assertEqual(headers["Content-Range"], f"bytes {start}-{last}/{total}")
        else:
            self.assertNotIn("Content-Range", headers)


class EofProbeProperties(SimpleTestCase):
    @given(total=st.integers(min_value=1, max_value=WINDOW),
           start=st.integers(min_value=0, max_value=WINDOW))
    # #216: a 1.5 MiB archive classified every seek as an EOF probe.
    @example(total=1_572_864, start=512_000)
    @example(total=1_572_864, start=1_048_576)
    def test_an_archive_no_larger_than_the_window_has_no_tail(self, total, start):
        self.assertFalse(ts_stats.is_near_eof_offset(start, total))
        self.assertFalse(ts_views._is_near_eof_probe(f"bytes={start}-", total))

    @given(total=st.integers(min_value=WINDOW + 1, max_value=10**12), data=st.data())
    def test_a_larger_archive_probes_exactly_in_its_last_window(self, total, data):
        start = data.draw(st.integers(min_value=0, max_value=total + WINDOW))
        expected = start >= total - WINDOW
        self.assertEqual(ts_stats.is_near_eof_offset(start, total), expected)
        self.assertEqual(ts_views._is_near_eof_probe(f"bytes={start}-", total), expected)

    @given(start=offsets)
    def test_unknown_length_probes_only_past_the_fixed_threshold(self, start):
        self.assertEqual(
            ts_views._is_near_eof_probe(f"bytes={start}-", None),
            start >= UNKNOWN_LENGTH_MIN,
        )

    @given(n=st.integers(min_value=1, max_value=10**9),
           total=st.none() | st.integers(min_value=1, max_value=10**12))
    @example(n=500, total=None)  # #141: bytes=-500 parsed as start 0
    def test_a_suffix_range_is_always_a_tail_probe(self, n, total):
        self.assertTrue(ts_views._is_near_eof_probe(f"bytes=-{n}", total))

    @given(header=st.none() | client_range_text,
           total=st.none() | st.integers(min_value=0, max_value=10**12).map(str)
           | st.text(max_size=6))
    @example(header="bytes=-²", total=None)
    def test_eof_probe_classification_never_raises(self, header, total):
        self.assertIsInstance(ts_views._is_near_eof_probe(header, total), bool)


class RangeRewriteProperties(SimpleTestCase):
    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9),
           span=st.none() | st.integers(min_value=-5, max_value=10**9))
    def test_cap_applies_only_to_open_ended_ranges_and_caps_to_exactly_the_span(
        self, start, length, span,
    ):
        header = f"bytes={start}-" if length is None else f"bytes={start}-{start + length}"
        capped = ts_views._cap_open_ended_range(header, span)
        if length is None and span is not None and span > 0:
            self.assertEqual(capped, f"bytes={start}-{start + span - 1}")
        else:
            self.assertEqual(capped, header)

    @given(header=st.none() | client_range_text, span=st.integers(min_value=1, max_value=10**9))
    def test_cap_returns_unparseable_headers_unchanged(self, header, span):
        if ts_views._parse_client_range(header) is None:
            self.assertEqual(ts_views._cap_open_ended_range(header, span), header)

    @given(header=st.none() | client_range_text)
    @example(header="bytes=0-")
    @example(header="")
    def test_full_restart_is_no_header_or_exactly_bytes_zero_open(self, header):
        expected = (not header) or ts_views._parse_client_range(header) == (0, None)
        self.assertEqual(ts_views._is_full_restart_range(header), expected)

    @given(start=offsets, length=st.none() | st.integers(min_value=0, max_value=10**9),
           base=st.integers(min_value=0, max_value=10**12))
    def test_presentation_mapping_shifts_both_offsets_by_the_base(self, start, length, base):
        header = f"bytes={start}-" if length is None else f"bytes={start}-{start + length}"
        mapped = ts_views._map_client_range_through_presentation(header, base)
        expected_end = None if length is None else base + start + length
        self.assertEqual(ts_views._parse_client_range(mapped), (base + start, expected_end))
        self.assertEqual(ts_views._map_client_range_through_presentation(header, None), header)

    @given(n=st.integers(min_value=1, max_value=10**9), base=st.integers(min_value=0, max_value=10**9))
    @example(n=500, base=50)  # #141: bytes=-500 became bytes=50-550, wider than asked
    def test_suffix_range_passes_through_the_presentation_mapping_unchanged(self, n, base):
        header = f"bytes=-{n}"
        self.assertEqual(ts_views._map_client_range_through_presentation(header, base), header)

    @given(base=st.integers(min_value=0, max_value=10**9),
           length=st.integers(min_value=1, max_value=10**9), data=st.data())
    def test_relative_content_range_inverts_the_mapping_inside_the_presentation(
        self, base, length, data,
    ):
        rel_start = data.draw(st.integers(min_value=0, max_value=length - 1))
        rel_end = data.draw(st.integers(min_value=rel_start, max_value=length - 1))
        upstream = f"bytes {base + rel_start}-{base + rel_end}/{base + length}"
        self.assertEqual(
            ts_views._presentation_relative_content_range(
                upstream, presentation_byte_base=base, presentation_length=length,
            ),
            f"bytes {rel_start}-{rel_end}/{length}",
        )

    @given(value=st.none() | content_range_text,
           base=st.integers(min_value=0, max_value=10**6),
           length=st.integers(min_value=1, max_value=10**6))
    # #141: a range starting before the presentation leaked the absolute CDN range.
    @example(value="bytes 400-499/1000", base=450, length=100)
    @example(value="bytes 100-50/1000", base=0, length=1000)
    def test_relative_content_range_is_none_or_inside_the_presentation(self, value, base, length):
        result = ts_views._presentation_relative_content_range(
            value, presentation_byte_base=base, presentation_length=length,
        )
        if result is None or not value:
            return
        parsed = ts_views._parse_content_range_header(result)
        self.assertIsNotNone(parsed, result)
        self.assertEqual(parsed["total"], length)
        self.assertLess(parsed["end"], length)
```

#### `apps/timeshift/tests/test_property_pool_decisions.py`

<!-- file: apps/timeshift/tests/test_property_pool_decisions.py -->
```python
"""Property tests for the catch-up pool-matching and preemption predicates.

Written against the contracts PR D-3 (#216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9), all in apps/timeshift/views.py:

- ``_score_pool_fingerprint`` (:1536) and ``_pool_entry_owned_by_user`` (:1705).
- ``_is_timeshift_startup_probe`` (:831) and ``_should_schedule_stats_disconnect_grace`` (:807).
- ``_should_preempt_plain_reconnect`` (:1318), ``_should_displace_busy_pool`` (:1245) and
  ``_should_displace_busy_playback`` (:1336). #216: a mid-file seek on an archive
  of 2 MiB or less was classified as an EOF probe, so it never displaced the busy pool.
- ``_resolve_session_archive_scrub`` (:2001): an in-session timestamp rebuild mapped
  to a TS-packet-aligned byte offset inside the already-open CDN file.
- ``_pool_int_field`` (:1935): Redis hash values in any spelling.

Closes #215's scope and the pool/``_pool_int_field`` scope of #192 (survivor).
"""

from datetime import datetime, timedelta

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.timeshift import views as ts_views

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_views._EOF_PROBE_TAIL_BYTES
MIN_BYTES = ts_views._STATS_GRACE_MIN_YIELDED_BYTES
MIN_SECS = ts_views._STATS_GRACE_MIN_ELAPSED_SECONDS

small_text = st.none() | st.text(max_size=8)
ids = st.none() | st.integers(min_value=0, max_value=50) | st.text(max_size=4)
range_headers = st.none() | st.sampled_from(["", "bytes=0-", "bytes=0-100", "bytes=-500"]) | (
    st.integers(min_value=0, max_value=10**10).map(lambda s: f"bytes={s}-")
) | st.text(max_size=16)


class _FakePoolRedis:
    """Only what _pool_session_exists reads: EXISTS on one pool key."""

    def __init__(self, present_key=None):
        self.present_key = present_key

    def exists(self, key):
        return 1 if key == self.present_key else 0


class FingerprintAndOwnershipProperties(SimpleTestCase):
    @given(entry_ip=small_text, entry_ua=small_text, ip=small_text, ua=small_text)
    def test_fingerprint_score_is_five_per_ip_match_plus_three_per_ua_match(
        self, entry_ip, entry_ua, ip, ua,
    ):
        entry = {"client_ip": entry_ip, "client_user_agent": entry_ua}
        expected = (5 if entry_ip and entry_ip == ip else 0) + (
            3 if entry_ua and entry_ua == ua else 0
        )
        score = ts_views._score_pool_fingerprint(entry, ip, ua)
        self.assertEqual(score, expected)
        self.assertLessEqual(score, ts_views._MATCH_SCORE_THRESHOLD)

    @given(profile_id=ids, owner=ids, user_id=st.integers(min_value=0, max_value=50))
    def test_unclaimed_entries_belong_to_anyone_and_claimed_ones_to_their_owner(
        self, profile_id, owner, user_id,
    ):
        entry = {"profile_id": profile_id, "user_id": owner}
        if not profile_id:
            expected = True
        elif owner is None or owner == "":
            expected = False
        else:
            expected = str(owner) == str(user_id)
        self.assertEqual(ts_views._pool_entry_owned_by_user(entry, user_id), expected)
        self.assertTrue(ts_views._pool_entry_owned_by_user({}, user_id))
        self.assertTrue(ts_views._pool_entry_owned_by_user(None, user_id))


class StatsGraceProperties(SimpleTestCase):
    @given(total=st.integers(min_value=0, max_value=10**8),
           elapsed=st.floats(min_value=0, max_value=3600, allow_nan=False))
    def test_startup_probe_is_the_conjunction_of_both_thresholds(self, total, elapsed):
        self.assertEqual(
            ts_views._is_timeshift_startup_probe(total, elapsed),
            total < MIN_BYTES and elapsed < MIN_SECS,
        )

    @given(total=st.integers(min_value=0, max_value=10**8),
           elapsed=st.floats(min_value=0, max_value=3600, allow_nan=False),
           stopped_for_reuse=st.booleans(), pool_exists=st.booleans(),
           client_id=st.none() | st.sampled_from(["", "sess-1"]))
    def test_grace_is_skipped_for_reuse_probes_and_an_early_retry_on_a_live_pool(
        self, total, elapsed, stopped_for_reuse, pool_exists, client_id,
    ):
        redis_client = _FakePoolRedis(
            ts_views._pool_key(client_id) if (pool_exists and client_id) else None
        )
        expected = not (
            stopped_for_reuse
            or (total < MIN_BYTES and elapsed < MIN_SECS)
            or (elapsed < MIN_SECS and bool(client_id) and pool_exists)
        )
        self.assertEqual(
            ts_views._should_schedule_stats_disconnect_grace(
                total, elapsed, stopped_for_reuse=stopped_for_reuse,
                redis_client=redis_client, client_id=client_id,
            ),
            expected,
        )


class PreemptionProperties(SimpleTestCase):
    @given(header=range_headers, pool_exists=st.booleans(), pool_busy=st.booleans(),
           pool_media_id=ids, media_id=ids)
    def test_plain_reconnect_preempts_exactly_a_full_restart_of_the_same_busy_media(
        self, header, pool_exists, pool_busy, pool_media_id, media_id,
    ):
        same_media = pool_media_id is None or str(pool_media_id) == str(media_id)
        expected = (
            ts_views._is_full_restart_range(header) and pool_exists and pool_busy and same_media
        )
        self.assertEqual(
            ts_views._should_preempt_plain_reconnect(
                header, pool_exists=pool_exists, pool_busy=pool_busy,
                pool_media_id=pool_media_id, media_id=media_id,
            ),
            expected,
        )

    @given(header=range_headers,
           content_length=st.none() | st.integers(min_value=1, max_value=10**10),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]),
           pool_media_id=ids, media_id=ids)
    def test_a_programme_hop_never_displaces_and_same_media_defers_to_the_playback_rule(
        self, header, content_length, busy_serving_range, pool_media_id, media_id,
    ):
        result = ts_views._should_displace_busy_pool(
            header, content_length, busy_serving_range,
            pool_media_id=pool_media_id, media_id=media_id,
        )
        if pool_media_id is not None and str(pool_media_id) != str(media_id):
            self.assertFalse(result)
        else:
            self.assertEqual(
                result,
                ts_views._should_displace_busy_playback(
                    header, content_length, busy_serving_range,
                ),
            )

    @given(total=st.integers(min_value=1, max_value=10**11), data=st.data(),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]))
    # #216: on a 1.5 MiB archive every mid-file seek was an "EOF probe" and never displaced.
    @example(total=1_572_864, data=None, busy_serving_range="start")
    def test_a_mid_file_seek_outside_the_tail_displaces_whatever_the_archive_size(
        self, total, data, busy_serving_range,
    ):
        if data is None:
            start = 512_000
        else:
            upper = total - WINDOW - 1 if total > WINDOW else total - 1
            if upper < 1:
                return
            start = data.draw(st.integers(min_value=1, max_value=upper))
        self.assertTrue(
            ts_views._should_displace_busy_playback(
                f"bytes={start}-", total, busy_serving_range,
            )
        )

    @given(content_length=st.none() | st.integers(min_value=1, max_value=10**10),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]))
    def test_a_byte_zero_seek_displaces_only_a_known_full_file_stream(
        self, content_length, busy_serving_range,
    ):
        self.assertEqual(
            ts_views._should_displace_busy_playback("bytes=0-", content_length, busy_serving_range),
            busy_serving_range == "none"
            and not ts_views._is_near_eof_probe("bytes=0-", content_length),
        )
        self.assertFalse(
            ts_views._should_displace_busy_playback(None, content_length, busy_serving_range)
        )


ANCHOR = datetime(2026, 3, 1, 20, 0, 0)


def _descriptor(content_length, duration_secs, anchor=ANCHOR):
    return {
        "final_url": b"https://cdn.example/archive.ts",
        "content_length": str(content_length),
        "archive_duration_secs": str(duration_secs),
        "archive_anchor_ts": anchor.strftime("%Y-%m-%d:%H-%M-%S").encode(),
    }


class ArchiveScrubProperties(SimpleTestCase):
    @given(content_length=st.integers(min_value=1, max_value=10**11),
           duration_secs=st.integers(min_value=60, max_value=8 * 3600),
           offset_secs=st.integers(min_value=-4 * 3600, max_value=10 * 3600))
    def test_scrub_is_same_in_window_aligned_or_none(
        self, content_length, duration_secs, offset_secs,
    ):
        requested = (ANCHOR + timedelta(seconds=offset_secs)).strftime("%Y-%m-%d:%H-%M-%S")
        result = ts_views._resolve_session_archive_scrub(
            _descriptor(content_length, duration_secs), requested,
        )
        if offset_secs == 0:
            self.assertEqual(
                result, {"kind": "same", "byte_offset": 0, "remaining": content_length},
            )
        elif offset_secs < 0 or offset_secs >= duration_secs:
            self.assertIsNone(result)
        elif result is not None:
            self.assertEqual(result["kind"], "scrub")
            offset = result["byte_offset"]
            self.assertEqual(offset % 188, 0)
            self.assertGreaterEqual(offset, 0)
            self.assertLess(offset, content_length)
            self.assertEqual(result["remaining"], content_length - offset)
            expected = (int(offset_secs / duration_secs * content_length) // 188) * 188
            self.assertEqual(offset, expected)

    @given(requested=st.text(max_size=24),
           descriptor=st.fixed_dictionaries({}, optional={
               # Pool hashes hold what Dispatcharr wrote: UTF-8 text, as str or as bytes.
               "final_url": st.none() | st.text(max_size=8)
               | st.text(max_size=8).map(str.encode),
               "content_length": st.none() | st.text(max_size=6) | st.integers(-5, 10**9),
               "archive_duration_secs": st.none() | st.text(max_size=6) | st.integers(-5, 10**5),
               "archive_anchor_ts": st.none() | st.text(max_size=20),
           }))
    def test_scrub_never_raises_on_arbitrary_pool_state(self, requested, descriptor):
        result = ts_views._resolve_session_archive_scrub(descriptor, requested)
        self.assertTrue(result is None or result["kind"] in {"same", "scrub"})


class PoolIntFieldProperties(SimpleTestCase):
    @given(n=st.integers(min_value=-(10**15), max_value=10**15),
           spelling=st.sampled_from(["int", "str", "bytes", "padded"]))
    def test_integer_spellings_round_trip(self, n, spelling):
        value = {
            "int": n, "str": str(n), "bytes": str(n).encode(), "padded": f" {n} ",
        }[spelling]
        self.assertEqual(ts_views._pool_int_field(value), n)

    # Redis-shaped values only: a hash field is None, str, bytes or (from a caller's own
    # dict) int. A float never reaches it; _pool_int_field(float("inf")) would raise.
    @given(value=st.none() | st.text(max_size=10) | st.binary(max_size=10)
           | st.integers())
    @example(value=b"\xff")
    @example(value="²")
    def test_anything_else_is_none_or_an_int_and_never_raises(self, value):
        result = ts_views._pool_int_field(value)
        self.assertTrue(result is None or isinstance(result, int))
```

#### `apps/timeshift/tests/test_property_stats.py`

<!-- file: apps/timeshift/tests/test_property_stats.py -->
```python
"""Property tests for catch-up playback-position math and stats field helpers.

Written against the contracts PR D-3 (#216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9):

- apps/timeshift/stats.py: ``stream_stats_to_metadata_fields`` (:47), ``_decode_hash``
  (:124), ``compute_playback_base_from_byte_range`` (:130),
  ``resolve_stats_playback_fields`` (:146; D-3 routes its tail check through
  ``is_near_eof_offset``, #216), ``compute_playback_position_secs`` (:219),
  ``_client_paused`` (:296).
- apps/timeshift/redis_keys.py: ``stats_channel_id`` (:73) and ``parse_stats_channel_id``
  (:88).

Anchors are realistic epoch seconds. #54 reported "position freezes at 0" and was ruled
invalid: its generator drew ``position_anchor_at=0.0``, which is falsy, and a real epoch
anchor never is.

Closes the stats scope of #192 (survivor), #260 and #55.
"""

import secrets

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.proxy.constants import ChannelMetadataField
from apps.timeshift import stats as ts_stats
from apps.timeshift.redis_keys import parse_stats_channel_id, stats_channel_id

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_stats.EOF_PROBE_TAIL_BYTES
# The ten Stream.stream_stats keys the stats card shows (stats.py:23-34), spelled out
# here rather than read from the module so a dropped mapping is caught.
MAPPED_SOURCE_KEYS = {
    "video_codec", "resolution", "source_fps", "pixel_format", "video_bitrate",
    "audio_codec", "sample_rate", "audio_channels", "audio_bitrate", "stream_type",
}

# Real epoch seconds: 2001-09-09 .. 2286-11-20 (see #54 in the module docstring).
epochs = st.floats(min_value=1_000_000_000, max_value=9_999_999_999, allow_nan=False)
durations = st.floats(min_value=1, max_value=12 * 3600, allow_nan=False)
stat_values = st.none() | st.just("") | st.text(max_size=8) | st.integers() | st.floats(
    allow_nan=False
)


class MetadataFieldProperties(SimpleTestCase):
    @given(stream_stats=st.none() | st.dictionaries(
        st.sampled_from(sorted(MAPPED_SOURCE_KEYS)) | st.text(max_size=8), stat_values,
        max_size=12,
    ))
    def test_only_mapped_non_empty_values_pass_through_as_text(self, stream_stats):
        out = ts_stats.stream_stats_to_metadata_fields(stream_stats)
        kept = {
            k: v for k, v in (stream_stats or {}).items()
            if k in MAPPED_SOURCE_KEYS and v is not None and v != ""
        }
        updated = ChannelMetadataField.STREAM_INFO_UPDATED
        self.assertEqual(updated in out, bool(kept))
        body = {k: v for k, v in out.items() if k != updated}
        self.assertEqual(len(body), len(kept))
        self.assertEqual(sorted(body.values()), sorted(str(v) for v in kept.values()))

    @given(data=st.none() | st.dictionaries(
        st.text(max_size=6) | st.text(max_size=6).map(str.encode),
        st.text(max_size=6) | st.text(max_size=6).map(str.encode),
        max_size=6,
    ))
    def test_decode_hash_yields_text_and_is_idempotent(self, data):
        decoded = ts_stats._decode_hash(data)
        for key, value in decoded.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)
        self.assertEqual(ts_stats._decode_hash(decoded), decoded)
        if not data:
            self.assertEqual(decoded, {})

    @given(value=st.none() | st.text(max_size=8) | st.text(max_size=8).map(str.encode),
           spelling=st.sampled_from([None, "1", "TRUE", " yes ", "Yes\n", "true"]))
    def test_paused_is_one_true_or_yes_in_any_case_and_padding(self, value, spelling):
        if spelling is not None:
            value = spelling
        text = value.decode() if isinstance(value, bytes) else value
        expected = text is not None and text.strip().lower() in {"1", "true", "yes"}
        self.assertEqual(ts_stats._client_paused(value), expected)


class PlaybackBaseProperties(SimpleTestCase):
    @given(range_start=st.none() | st.integers(min_value=-10, max_value=10**11),
           content_length=st.integers(min_value=-10, max_value=10**11),
           duration=st.floats(min_value=-10, max_value=12 * 3600, allow_nan=False))
    def test_byte_offset_maps_linearly_into_the_programme_or_none(
        self, range_start, content_length, duration,
    ):
        base = ts_stats.compute_playback_base_from_byte_range(
            range_start, content_length, duration,
        )
        if range_start is None or range_start <= 0 or content_length <= 0 or duration <= 0:
            self.assertIsNone(base)
            return
        expected = min(1.0, range_start / content_length) * duration
        self.assertAlmostEqual(base, expected, places=6)
        self.assertGreaterEqual(base, 0.0)
        self.assertLessEqual(base, duration)

    @given(total=st.integers(min_value=1, max_value=WINDOW), data=st.data(),
           duration=durations, previous_base=st.floats(0, 3600, allow_nan=False),
           previous_anchor=epochs, now=epochs)
    # #216: on a 1.5 MiB archive a mid-file seek kept the previous stats base.
    @example(total=1_572_864, data=None, duration=3600.0, previous_base=120.0,
             previous_anchor=1_700_000_000.0, now=1_700_000_100.0)
    def test_a_seek_into_an_archive_no_larger_than_the_window_reanchors(
        self, total, data, duration, previous_base, previous_anchor, now,
    ):
        if data is None:
            start = 512_000
        elif total > 1:
            start = data.draw(st.integers(min_value=1, max_value=total - 1))
        else:
            return
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start="2026-03-01:20-00",
            existing_position_anchor=str(previous_anchor),
            existing_playback_base=str(previous_base), range_start=start,
            representation_length=total, programme_duration_secs=duration, now=now,
        )
        self.assertEqual(anchor, now)
        self.assertAlmostEqual(base, min(1.0, start / total) * duration, places=6)

    @given(total=st.integers(min_value=WINDOW + 1, max_value=10**11), data=st.data(),
           previous_base=st.floats(0, 3600, allow_nan=False), previous_anchor=epochs,
           now=epochs)
    def test_a_tail_probe_on_a_larger_archive_keeps_the_previous_anchor(
        self, total, data, previous_base, previous_anchor, now,
    ):
        start = data.draw(st.integers(min_value=total - WINDOW, max_value=total - 1))
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start=b"2026-03-01:20-00",
            existing_position_anchor=str(previous_anchor).encode(),
            existing_playback_base=str(previous_base).encode(), range_start=start,
            representation_length=total, programme_duration_secs=3600, now=now,
        )
        self.assertEqual((base, anchor), (previous_base, str(previous_anchor)))

    @given(range_start=st.none() | st.integers(min_value=0, max_value=10**11),
           total=st.none() | st.integers(min_value=0, max_value=10**11),
           existing_start=st.none() | st.text(max_size=16),
           previous_base=st.none() | st.text(max_size=6) | st.floats(0, 1e5, allow_nan=False).map(str),
           now=epochs)
    def test_resolve_never_raises_and_a_programme_change_always_reanchors_at_url_time(
        self, range_start, total, existing_start, previous_base, now,
    ):
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start=existing_start,
            existing_position_anchor=None, existing_playback_base=previous_base,
            range_start=range_start, representation_length=total,
            programme_duration_secs=3600, now=now,
        )
        if base is not None:
            self.assertGreaterEqual(base, 0.0)
        if existing_start is not None and existing_start != "2026-03-01:20-00":
            self.assertEqual((base, anchor), (None, now))


class PlaybackPositionProperties(SimpleTestCase):
    @given(base=st.floats(min_value=0, max_value=12 * 3600, allow_nan=False),
           anchor=epochs, elapsed=st.floats(min_value=-600, max_value=12 * 3600, allow_nan=False),
           duration=st.none() | durations, paused=st.booleans())
    def test_byte_seek_position_is_base_plus_unpaused_elapsed_clamped_to_the_programme(
        self, base, anchor, elapsed, duration, paused,
    ):
        position = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor + elapsed, duration_secs=duration,
            playback_base_secs=base, paused=paused,
        )
        expected = base + (0.0 if paused else max(0.0, elapsed))
        if duration:
            expected = min(expected, duration)
        self.assertAlmostEqual(position, expected, delta=1e-6 * max(1.0, expected))

    @given(url_offset_secs=st.integers(min_value=-3600, max_value=6 * 3600),
           anchor=epochs, elapsed=st.floats(min_value=0, max_value=6 * 3600, allow_nan=False),
           duration=durations, paused=st.booleans())
    def test_url_seek_position_is_offset_from_epg_start_plus_elapsed_never_negative(
        self, url_offset_secs, anchor, elapsed, duration, paused,
    ):
        from datetime import datetime, timedelta

        epg_start = datetime(2026, 3, 1, 20, 0, 0)
        url = (epg_start + timedelta(seconds=url_offset_secs)).strftime("%Y-%m-%d:%H-%M-%S")
        position = ts_stats.compute_playback_position_secs(
            url, epg_start.isoformat() + "+00:00", anchor, anchor + elapsed,
            duration_secs=duration, paused=paused,
        )
        expected = min(max(0.0, url_offset_secs + (0.0 if paused else elapsed)), duration)
        self.assertAlmostEqual(position, expected, delta=1e-6 * max(1.0, expected))

    @given(anchor=epochs, later=st.floats(min_value=0, max_value=86400, allow_nan=False),
           base=st.floats(min_value=0, max_value=3600, allow_nan=False))
    def test_paused_position_does_not_advance_with_the_wall_clock(self, anchor, later, base):
        first = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor, playback_base_secs=base, paused=True,
        )
        second = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor + later, playback_base_secs=base, paused=True,
        )
        self.assertEqual(first, second)


session_ids = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1, max_size=32,
)


class StatsChannelIdProperties(SimpleTestCase):
    @given(channel_id=st.integers(min_value=0, max_value=10**9), session_id=session_ids)
    def test_minted_stats_channel_ids_round_trip(self, channel_id, session_id):
        self.assertEqual(
            parse_stats_channel_id(stats_channel_id(channel_id, session_id)),
            {"channel_id": channel_id, "session_id": session_id},
        )

    def test_a_real_minted_session_id_round_trips(self):
        session_id = secrets.token_urlsafe(16)
        self.assertEqual(
            parse_stats_channel_id(stats_channel_id(7, session_id))["session_id"], session_id,
        )

    @given(value=st.none() | st.text(max_size=24) | st.integers())
    def test_parse_is_none_or_a_numeric_channel_and_a_session(self, value):
        parsed = parse_stats_channel_id(value)
        if parsed is not None:
            self.assertIsInstance(parsed["channel_id"], int)
            self.assertTrue(parsed["session_id"])

    @given(prefix=st.text(alphabet="abc-_ ", min_size=1, max_size=6), session_id=session_ids)
    def test_an_id_without_a_numeric_prefix_is_rejected(self, prefix, session_id):
        self.assertIsNone(parse_stats_channel_id(f"{prefix}_{session_id}"))
```

