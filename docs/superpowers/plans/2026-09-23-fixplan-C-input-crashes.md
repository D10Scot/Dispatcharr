# Fix plan, category C — crashes on provider- or client-controlled input

**Category.** C: sixteen tracker issues, fourteen distinct defects, where a value the operator does not
control (a provider's playlist bytes, a channel name, an XMLTV attribute, a query parameter, a JSON
field) reaches code that assumes it is well-formed. Most came from the domain-fuzz campaign with a
shrunk counterexample in the issue body. Every counterexample below becomes an example-based regression
test named after the defect.

**Seed SHA: `a54b09a9`** (`main`, 2026-09-23). Every `file:line` below was opened there; every
counterexample was re-run there inside a private test container (`fixplan-C`, bind-mounted at this
plan's worktree) unless a row says otherwise.

**Ordering position.** Fourth of ten: B, A, J, **C**, D, E, G, H, I, F. The lead re-seeds this plan
when an earlier category's plan merges. Nothing in this plan depends on B, A or J *merging first*; the
overlap section says where a rebase will meet their edits.

**Architecture.** Django 6 + DRF control plane with Celery workers; the live relay is the Go binary in
`relay/` and is untouched here. Every fix in this plan is in Django-side Python or a Django migration.

**Tech stack.** Python 3.13, Django 6, the third-party `regex` module (already a dependency and
already the engine for rename, URL-transform and preview patterns), lxml.

**Planner's worktree.** `.worktrees/fixplan-C`, branch `docs/fixplan-C`. Only this file is committed.

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
   and after assertion. Never widen a tolerance, lower a count or delete an assertion to make a run
   green. New behaviour gets a new test named after the defect. **No PR in this plan changes an
   existing test**; each section says so explicitly and names the existing tests that must stay green
   unmodified.
5. **Break-check every new test.** Each task names one deliberate wrong edit. Make it, run the new
   test, confirm it fails *with a message naming the mechanism* (not an import error or a side
   effect of the edit), revert, confirm green. Record the failure line in the PR description.
6. **Test container.** Hooks always use the shared container `dispatcharr-testrunner`, whose mount
   decides which tree is tested (`CLAUDE.md` § Test hooks). Re-point it at your worktree only after the
   occupancy check (`docker ps --filter name=dispatcharr-testrunner` plus mtimes); for runs you launch
   yourself prefer a private container:
   `DISPATCHARR_TEST_CONTAINER=fix-C-<n> DISPATCHARR_TEST_DB_VOLUME=fix-C-<n>-db CLAUDE_HOOK_REPO_ROOT=<wt> .claude/hooks/start-test-container.sh`.
   Run one label at a time (`manage.py test --keepdb <label>`) and **once without `--keepdb`** before
   push (the seeded-row drift trap).
7. **No category-I work.** These PRs add no `test_property_*` module, no `@given`, and no Hypothesis
   import. Where a category-I issue will later cover the same helper, the PR section names the seam.
8. **No `metrics/curated/` edits.** None of the sixteen issues has a `defects.yml` entry (checked:
   `grep -cE "^\s*issue:\s*<n>\s*$" metrics/curated/defects.yml` is `0` for all sixteen), none is a
   CLAUDE.md "Known defects" bullet, and none has an e2e `test.fail()` pin or a parity-matrix row.
   A PR that discovers otherwise STOPs and reports.
9. **Branch names** are `fix/C-<n>-<slug>`. No PR here touches `docker/`, `relay/httpapi/` or
   `docker/nginx.conf`, so none takes the `migration/` prefix.

---

## Files this plan touches

| file | PR |
|---|---|
| `apps/output/views.py` | C-1 |
| `apps/output/epg.py` | C-1 |
| `apps/epg/tasks.py` | C-2 |
| `apps/m3u/tasks.py` | C-3, C-4 |
| `apps/m3u/models.py` | C-3 |
| `apps/m3u/utils.py` | C-3, C-4 |
| `apps/proxy/next_source.py` (Gate 2 module) | C-4 |
| `apps/proxy/vod_proxy/views.py` | C-4 |
| `apps/m3u/connection_pool.py` | C-5 |
| `apps/vod/tasks.py` | C-6 |
| `apps/channels/migrations/0038_add_catchup_fields.py` | C-7 |
| `apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py` | C-7 |
| new test modules, one per defect family (named in each section) | all |

## Overlap with other categories

From `sweep-report.md` and the category issue files. "First" is the lead's ordering (B, A, J, C, D, E, G, H, I, F).

| file | other plan and what it is assumed to do there | who goes first | collision risk |
|---|---|---|---|
| `apps/m3u/tasks.py` | **B #61**: quote the credentials in `collect_xc_streams`'s live-URL prefix (`:942-945`). | B | None at function level. Line numbers below drift by a few lines. |
| `apps/m3u/tasks.py` | **E #56 / #60 / #70**: lock-miss return at `:1555`, the caller's generic message at `:3502-3514`, and the auto-sync SUCCESS at `:3891`. | C | **Real.** C-3 moves the body of `refresh_m3u_groups` into a new function and deletes its nine inline lock releases (Appendix B). E's #56 edits the lock-acquire line, which C-3 leaves in the outer function. E rebases onto C-3 and edits the outer function. |
| `apps/output/views.py` | **B #84 / #134 / #110**: `xc_get_user`, the XC 401s and the VOD listing filter. **D #97 / #94**: `xc_get_vod_info` and the M3U `#EXTINF`. **E #80 / #85**: `#EXTINF` escaping and `xc_get_live_categories`. | B, then C, then D and E | None. C-1 touches only `xc_get_epg` (`:785-940`). |
| `apps/proxy/vod_proxy/views.py` | **B #89 / #110**: the 500 body at `:862` and the adult filter at `:619`, `:1410`, `:1447`. **D #99**: `stream_xc_episode` at `:1468-1478`. | B, then C, then D | Low. C-4 edits one line of `_transform_url` (`:603`), thirteen lines above B's `:616-619` hunk. Expect a context-only rebase. |
| `apps/proxy/next_source.py` | **J-3**: a Django-side zero-ORM ratchet over `apps/proxy/{next_source,...}.py`. | J | None. C-4 adds an import from `apps.m3u.utils` and performs no ORM read, so the ratchet's allowlist is unaffected. |
| `apps/m3u/connection_pool.py`, `apps/m3u/models.py`, `apps/epg/tasks.py`, `apps/output/epg.py`, `apps/vod/tasks.py` | **I #145, #200, #218, #69, #274, #158, #202, #210, #162, #92, #243**: Hypothesis property tests over the same helpers. | C | None in code. I lands later and its properties assume C's fixes. The seams are named per PR below. |

---

## Duplicates

| survivor | duplicate | basis |
|---|---|---|
| **#91** | #212 | Same line (`apps/output/views.py:881`) and same fix. #212 adds only the negative-limit slice at `:921` and `:933`, which C-1 covers under #91. Named by the lead. |
| **#76** | #156 | Same function (`parse_xmltv_time` re-raising into the unguarded offset helpers) and same fix. #156 adds the second call site, `_scan_from_offset_for_tvg_id`, which C-2 covers under #76. Named by the lead. |
| **#90** (recommended) | #211 | **Not named by the lead; my recommendation.** Both issues report `generate_custom_dummy_programs` raising on an out-of-range captured minute or day, with the same root cause and the same fix. #211 adds the `OverflowError` variant, which C-1 covers. #90 is older (run 33323824654, against #211's 34189481579). C-1 closes both either way; the lead decides whether the tracker records a duplicate. |

---

## Per-issue analysis

Sizes: S is under 30 changed lines, M is under 150, L is more.

### #91 (and duplicate #212): `xc_get_epg` 500s on a non-numeric or negative `limit`

- **Root cause.** `apps/output/views.py:881` runs `limit = int(request.GET.get('limit', 4))` with no
  guard. The neighbouring `days` parse at `:882-887` is guarded. `limit` then slices a queryset at
  `:921` and `:933`, and Django refuses a negative slice.
- **Fix.** Parse inside `try/except (ValueError, TypeError)` and fall back to 4. Treat a negative value
  as 4 too. `0` stays `0`, which is today's behaviour.
- **Tests.** New file `apps/output/tests/test_xc_epg_limit_guard.py`, class `XcEpgLimitGuardTests`,
  built like `XcGetEpgCatchupGateTests` (`apps/output/tests/test_views.py:1271`), with six upcoming
  `ProgramData` rows and `xc_get_epg(request, user, short=True)`:
  `test_non_numeric_limit_falls_back_to_default_instead_of_500` (`limit=abc` returns four rows) and
  `test_negative_limit_falls_back_to_default_instead_of_500` (`limit=-5` returns four rows).
- **Size** S. **Upstreamable** yes: upstream `dev` carries the identical line at `apps/output/views.py:956`.

### #90 (and recommended duplicate #211): out-of-range time or date captured from a channel name crashes dummy-EPG generation and the whole XMLTV export

- **Root cause.** In `generate_custom_dummy_programs` (`apps/output/epg.py:258`) the `int()`
  conversions are guarded (`:434-460`, `:469-512`), but nothing range-checks the results before they
  reach `datetime` construction. `minute` is never checked. `hour` is checked only on the 24-hour arm
  (`:453-455`, which wraps modulo 24). The 12-hour arm can produce `hour=25` from `13:30pm`. The date
  check at `:506` accepts `1 <= day <= 31` for any month and never checks `year`. The values then
  raise at `:547` (`datetime(year, month, day)`), at `:554` and `:572` (`base_date.replace(hour,
  minute)`) and at `:604`. Nothing in the export loop (`:1652-1661`) catches it, so one channel aborts
  the streamed `/output/epg` body for every client.
- **Reproduced at seed.**

  | channel name and pattern | result |
  |---|---|
  | `Team A @ 10:75` (#90) | `ValueError: minute must be in 0..59` |
  | `Ch 10:99` (#211) | `ValueError: minute must be in 0..59` |
  | `C 10:99999999999999999999` (#211) | `OverflowError: Python int too large to convert to C int` |
  | `Game 2/31 @ 10:30` (#90, #211) | `ValueError: day is out of range for month` |
  | `X 13:30pm` on a 12-hour pattern (found here) | `ValueError: hour must be in 0..23` |
  | `X 1/2/0 10:30` and `1/2/99999` on a year pattern (found here) | `ValueError: year 0 is out of range`, and the same for 99999 |

  There is one more case, found by reading `:476` and `:504`. A pattern that captures a month but no day defaults the day to `now.day`. On the 29th to 31st that date is impossible in a short month, so the same crash happens on some calendar days only. The fix below closes it as well.
- **Fix.** Validate at the source, inside the two existing parse blocks, so `time_info` and `date_info`
  are either valid or `None`, exactly as for an unparseable capture today:
  - Time: after the existing 12/24-hour conversion and the existing `% 24` wrap (kept unchanged), accept
    only `0 <= hour <= 23 and 0 <= minute <= 59`. Otherwise log a WARNING naming both values and leave
    `time_info = None`.
  - Date: accept only `1 <= year <= 9999` and `1 <= month <= 12` and
    `1 <= day <= calendar.monthrange(year, month)[1]`. Evaluate the year and month bounds first, so
    `monthrange` never sees an invalid year. Hoist the local `import calendar` at `:488` to the top of
    the block.

  Every later consumer (`:540-720`) reads only `time_info` and `date_info`, so this one change covers
  all six construction sites. **No per-channel `try/except` is added to the export loop**: it would hide
  the next unvalidated path rather than fix this one.
- **Tests.** New file `apps/output/tests/test_custom_dummy_out_of_range_capture.py`:
  - `CustomDummyOutOfRangeCaptureTests(SimpleTestCase)` calls `generate_custom_dummy_programs` directly,
    one `subTest` per counterexample row above:
    `test_out_of_range_minute_is_treated_as_no_time_instead_of_raising` (`10:75`, `10:99`, the
    20-digit minute),
    `test_twelve_hour_capture_past_midnight_is_treated_as_no_time`,
    `test_impossible_calendar_date_is_treated_as_no_date` (`2/31`),
    `test_out_of_range_year_is_treated_as_no_date` (`0`, `99999`). Each asserts that the call returns a
    list and emits one WARNING from `apps.output.epg` (`assertLogs`).
  - `CustomDummyExportSurvivesBadChannelNameTests(TestCase)`,
    `test_one_out_of_range_channel_name_does_not_abort_the_xmltv_export`: one dummy source configured
    with #90's patterns, two channels (one named `Team A @ 10:75`, one well-formed), and a request to the
    XMLTV endpoint through `OutputEndpointTestMixin` (`apps/output/tests/test_views.py:42`). It asserts
    a 200, a body ending in `</tv>`, and a `<programme` for the well-formed channel.
- **Size** M. **Upstreamable** partly. `generate_custom_dummy_programs` is not in upstream `dev`'s
  `apps/output/epg.py` (658 lines there against the fork's larger file), so that half needs a port.

### #76 (and duplicate #156): a malformed XMLTV timestamp 500s `POST /api/epg/programs/current/`

- **Root cause.** `parse_xmltv_time` logs and re-raises every failure (`apps/epg/tasks.py:2542-2544`).
  The bulk parsers catch per element (`:1730`, `:2222`), but the two byte-offset helpers do not:
  `_read_programs_at_offsets` at `:3211-3212` and `_scan_from_offset_for_tvg_id` at `:3304-3305`. Their
  `if start_time is None` guards on the next line are dead code. The exception escapes
  `find_current_program_for_tvg_id` into `CurrentProgramsAPIView.post` at `apps/epg/api_views.py:845`,
  which has no `try`, so the whole multi-channel request returns 500.
- **Fix.** Wrap both pairs of calls in `try: ... except (ValueError, TypeError): continue`, so a bad
  programme is skipped and the scan moves on, as the bulk parser does. **`parse_xmltv_time` keeps its
  raising contract**, because both bulk callers rely on it. Its per-failure ERROR log with traceback stays
  as it is. That is noisy when the dashboard polls, but it is a logging choice and not this defect.
- **Tests.** New file `apps/epg/tests/test_malformed_xmltv_timestamp.py`:
  `test_malformed_offset_is_skipped_by_offset_lookup_not_raised` uses #76's harness verbatim: a
  `+2400` programme, then an always-on programme, through `_read_programs_at_offsets`, which must return
  "Always On".
  `test_malformed_offset_is_skipped_by_interleaved_scan_not_raised` does the same through
  `_scan_from_offset_for_tvg_id`, using #156's `+2460` counterexample.
  `test_current_programs_api_does_not_500_on_a_malformed_programme_timestamp` builds a real temp file,
  `build_programme_index` and an `EPGData` with no DB programme, then POSTs to the endpoint. It asserts a
  200 carrying the valid programme. Setup mirrors
  `apps/epg/tests/test_programme_index.py:170-205`.
- **Size** S. **Upstreamable** yes: upstream `dev`'s `apps/epg/tasks.py` has the same helpers.

### #75: an XMLTV offset written without a space is dropped and the time is read as UTC

- **Root cause.** `apps/epg/tasks.py:2516` applies an offset only when `len(time_str) >= 20`, which
  assumes a space at index 14. `20260728183000+0530` has 19 characters, takes the no-timezone branch at
  `:2536-2538` and is stored 5h30 late.
- **Reproduced at seed.**

  | input | result |
  |---|---|
  | `20260728183000+0530` | `18:30 UTC`; the correct value is 13:00 |
  | `20260728183000-0800` | `18:30 UTC`; the correct value is 02:30 the next day |
- **Fix.** Before the branch, if `len(time_str) >= 19` and `time_str[14]` is `+` or `-`, insert the
  missing space: `time_str = time_str[:14] + ' ' + time_str[14:]`. Every other shape keeps its current
  behaviour, including the short-string path, the 18-character `+05` case and a non-sign character at
  index 15.
- **Tests.** In the same new module:
  `test_adjacent_positive_offset_is_applied_not_read_as_utc` (the issue's counterexample, which must be
  13:00 UTC),
  `test_adjacent_negative_offset_is_applied_not_read_as_utc` (`-0800`, which must be 02:30 on the 29th),
  and `test_spaced_offset_still_parses_the_same` as a control that must stay green.
- **Size** S. **Upstreamable** yes: upstream `dev` has the same condition at `apps/epg/tasks.py:2624`.

### #157: programme-index keys disagree with `EPGData.tvg_id` for some entity-bearing or whitespace-bearing channel ids

- **Root cause.** The index key comes from `_decode_channel_id` (`apps/epg/tasks.py:2902-2907`), which
  applies `html.unescape`. The database value comes from lxml `iterparse(recover=True)` over
  `_open_xmltv_file`, which prepends an HTML 4 entity DOCTYPE **unless the file already declares one**
  (`:307`). The two rules disagree, so `find_current_program_for_tvg_id` looks up a key the index never
  stored and reports no programme.
- **Measured at seed: the assessor's "HTML5-only" correction is too narrow.** Each row is lxml's value
  (what lands in the database) against `_decode_channel_id`'s value (the index key):

  | `programme@channel` raw | lxml | index | agree |
  |---|---|---|---|
  | `a&NewLine;b` (HTML5-only name) | `ab` | `a\nb` | no |
  | `a&eacute;b`, DOCTYPE injected | `aéb` | `aéb` | yes |
  | `a&eacute;b`, **file carries its own DOCTYPE** | `ab` | `aéb` | **no** |
  | `a&#233;b` | `aéb` | `aéb` | yes |
  | `a<TAB>b` (a literal tab) | `a b` | `a\tb` | **no** |
  | `a&eacuteb` (no semicolon) | `a` | `aéb` | **no** |

  So the issue body's original scope (HTML 4 names too) is right whenever the file carries its own DOCTYPE, and two
  further shapes diverge that neither the issue nor the assessor names.
- **Fix.** Make `_decode_channel_id` produce lxml's value by asking lxml, the same way the file parse does:
  - Extract `_xmltv_file_gets_entity_doctype(file_path) -> bool` from `_open_xmltv_file`, which then
    calls it. The DOCTYPE check at `:302-308` moves into the helper unchanged.
  - Change the signature to `_decode_channel_id(raw, quote=b'"', entity_doctype=True)`. If `raw`
    contains no `&` and none of `\t`, `\n`, `\r`, keep today's decode-and-strip fast path. Otherwise
    parse `b'<p c=' + quote + raw + quote + b'/>'` with `etree.XMLParser(recover=True,
    remove_blank_text=True)`, prefixing `_HTML_ENTITY_DOCTYPE` only when `entity_doctype`, then read
    `c` and strip it. Cache with `functools.lru_cache(maxsize=4096)`, because channel ids repeat once
    per programme. Measured uncached cost is about 60 µs per call.
  - The three callers (`build_programme_index` at `:3007`, and the two helpers at `:3184` and `:3277`)
    compute `entity_doctype` once per file and pass the quote their regex group matched. Appendix A has
    the hunks.

  A prototype of exactly this shape agreed with lxml on all six rows above. It also agreed on the two
  shapes the existing tests pin: `" A&amp;E.us "` with surrounding spaces, and single-quoted `it&apos;s`.
- **Tests.** New file `apps/epg/tests/test_channel_id_entity_parity.py`:
  `test_index_key_equals_lxml_value_for_every_divergent_channel_id` uses one `subTest` per table row,
  six in all. Each writes a temp XMLTV file, takes lxml's value through `_open_xmltv_file` plus
  `iterparse`, and compares it with the key `build_programme_index` stored. The oracle is lxml's own
  file parse, which the new code never calls, so the test is not tautological.
  `test_current_programme_found_for_html5_entity_channel_id` and
  `test_current_programme_found_when_file_declares_its_own_doctype` each run
  `find_current_program_for_tvg_id` against an `EPGData` whose `tvg_id` is the lxml value. Each must
  return the airing programme.
  The existing `test_channel_id_entities_and_whitespace_match_tvg_id`
  (`test_programme_index.py:170`) and the single-quote test at `:406` must stay green unmodified.
- **Size** M. **Upstreamable** yes: upstream `dev` has `_decode_channel_id` at `apps/epg/tasks.py:3001`.

### #262: stream filters run user-authored regexes with stdlib `re` and no timeout

- **Root cause.** `_compile_m3u_stream_filters` (`apps/m3u/tasks.py:1017-1027`) calls `re.compile`,
  and `_stream_passes_m3u_filters` (`:1030-1044`) calls `pattern.search` once per stream per refresh
  with no bound. `M3UFilter.applies_to` (`apps/m3u/models.py:198-200`) has the same unbounded
  `re.search` and no non-test callers. The rename path at `apps/m3u/tasks.py:2604-2613` already uses
  `regex` with `timeout=` for exactly this reason.
- **Measured at seed.** stdlib `re`: `(a+)+$` against `"a"*24 + "b"` took 0.60 s, and `^(a|a?)+$`
  took 2.40 s. `regex` optimises both to 0.0 s, but it still times out on `(a|a)+b` and on `(a|a)*$`,
  which is the house test idiom at `tests/test_websocket_consumer_filter.py:271`. So the engine
  change alone fixes the issue's counterexample, and the timeout is needed for the rest.
- **Fix.**
  - Compile with `regex.compile(..., regex.IGNORECASE or 0)`.
  - Wrap each compiled pattern in a small `_BoundedFilterPattern` that exposes `.pattern` and
    `.search(target)`. Every search passes `timeout=M3U_FILTER_REGEX_TIMEOUT`, a new 0.1 s constant in
    `apps/m3u/utils.py` beside the rename path's value.
  - On `TimeoutError` the wrapper sets `tripped`, logs one WARNING naming the pattern, and from then on
    returns `None` (non-matching) for the rest of that compiled set, that is, for that refresh. Without
    the trip, one pathological filter still costs 0.1 s times the stream count, about 17 minutes for
    10,000 streams.

  The compiled list is shared across `ThreadPoolExecutor` batch workers in one process
  (`:3612-3620`, `:3752-3758`), so a plain attribute is enough; two concurrent trips log twice, which
  is harmless. A timed-out *exclude* filter now lets streams through, which is fail-open. That is the
  rename path's policy and the issue's suggestion, and the PR description must say so. `applies_to`
  switches to `regex.search(..., timeout=)` and returns `False` on timeout. `clean()` is left alone:
  it validates with `re`, whose accepted syntax is a subset of `regex`'s, so it cannot reject a
  pattern the runtime would accept.
- **Tests.** Appended to `apps/m3u/tests/test_stream_filters.py` as a new class
  `StreamFilterRegexTimeoutTests(SimpleTestCase)`:
  - `test_nested_quantifier_filter_does_not_stall_refresh` uses the issue's counterexample verbatim,
    `(a+)+$` against `"a"*28 + "b"`, and asserts it finishes in under
    `M3U_FILTER_REGEX_TIMEOUT * 20`.
  - `test_filter_search_that_times_out_is_non_matching_and_warned_once` runs an exclude filter
    `(a|a)*$` over three names `"a"*28 + "!"`. All three must pass, with exactly one WARNING.
  - `test_applies_to_is_time_bounded` checks the same bound through `M3UFilter.applies_to`.

  All nine existing tests in the module must stay green unmodified. They call `.search` and read
  `.pattern` on the compiled object, and the wrapper keeps both.
- **Size** S. **Upstreamable** yes: upstream `dev` has the `re.compile` line at `apps/m3u/tasks.py:1035`.

### #217: a non-UTF-8 playlist raises `UnicodeDecodeError` and leaks the group-refresh lock

- **Root cause, wider than the issue.**
  - The ZIP branch decodes strict UTF-8 at `apps/m3u/tasks.py:551`, outside the `except` tuple at
    `:569`.
  - **The plain, `.gz` and `.xz` paths open strict UTF-8 as well** (`_open_m3u_text_source`,
    `:172-175`). That covers every URL-downloaded playlist too. The error surfaces while iterating at
    `:1763-1767` inside `refresh_m3u_groups`, again with no handler. Reproduced at seed: a Latin-1
    `.m3u` raises `UnicodeDecodeError ... byte 0xe9`.
  - **The lock consequence is worse than the issue says.** On any escaped exception
    `refresh_m3u_groups` skips both `lock_renewer.stop()` and `release_task_lock(...)`. The
    `TaskLockRenewer` daemon thread (`core/utils.py:327-385`) keeps extending the lock's TTL every 120 s
    for as long as the lock key exists. So the lock is held for the life of the worker process, not
    "until the 300 s TTL".
  - Reached through `refresh_single_m3u_account`, the account does land in ERROR, because that
    wrapper has its own `try/finally` (`:3381-3399`). Reached as the standalone task, it stays in
    whatever status it had.
- **Fix, in two parts.**
  1. **Decode leniently, and correctly for the common case.** Register one codec error handler in
     `apps/m3u/utils.py`, `m3u_cp1252_fallback`, which decodes each invalid byte run as cp1252 (with
     `replace` for cp1252's five undefined bytes). Use `errors="m3u_cp1252_fallback"` at all four
     sites: `:172`, `:174`, `:175` and `:551`. Valid UTF-8 is unchanged. A Latin-1 or Windows-1252
     provider gets `Séries`, not `S�ries`. `_open_m3u_text_source` still returns a text file, so
     `test_xz_playlist.py`'s `.read()` assertions hold. See the open questions for the alternative.
  2. **Release the lock on every exit.** Split `refresh_m3u_groups` the same way
     `refresh_single_m3u_account` is already split. The outer function acquires the lock, starts the
     renewer, and runs `try: return _refresh_m3u_groups_locked(...)` with `finally:
     lock_renewer.stop(); release_task_lock(...)`. The old body, from `:1560` to `:1838`, becomes the
     inner function **with its nine inline stop-and-release pairs deleted** (`:1563-1564`, `:1595-1596`,
     `:1608-1609`, `:1680-1681`, `:1719-1720`, `:1736-1737`, `:1748-1749`, `:1755-1756`,
     `:1820-1821`). A `try/except` that released only on failure was rejected, because after the
     body's own release at `:1821` a later exception would delete a lock another task had since taken.
     The one ordering change is that on a non-full refresh the lock now drops after the
     `PENDING_SETUP` update (`:1823-1835`) rather than before it. Nothing in that update depends on the
     lock. Appendix B has the shape.
- **Tests.** New file `apps/m3u/tests/test_non_utf8_playlist.py`:
  - `test_zip_upload_with_latin1_playlist_does_not_raise` uses the issue's harness verbatim through
    `fetch_m3u_lines`. It asserts success and a line containing `TF1 Séries HD`.
  - `test_latin1_playlist_parses_on_the_streamed_paths` runs one `subTest` each for `.m3u`, `.m3u.gz`
    and `.m3u.xz` through `_open_m3u_text_source` plus `iter_m3u_entries`. Each asserts the entry name
    `TF1 Séries HD`.
  - `test_valid_utf8_playlist_is_decoded_unchanged` is a control.
  - `test_unexpected_exception_in_group_refresh_releases_the_lock_and_stops_the_renewer` needs the DB
    and Redis. It creates a STD account with `server_url`, patches `apps.m3u.tasks.fetch_m3u_lines`
    to raise `RuntimeError`, and calls `refresh_m3u_groups(account.id)`, which must raise. Afterwards
    `acquire_task_lock("refresh_m3u_account_groups", account.id)` must return `True`, and no thread
    named `lock-renew-refresh_m3u_account_groups-<id>` may be alive. The test releases the lock
    afterwards.
- **Size** M. **Upstreamable** yes: upstream `dev` has the same decode sites at
  `apps/m3u/tasks.py:182-185` and `:549`.

### #199: out-of-range `exp_date` or a non-dict `user_info` crashes profile `save()` and the admin page

- **Root cause.**
  - `_parse_exp_date` (`apps/m3u/models.py:306-321`) catches `(ValueError, TypeError, OSError)` at
    `:319`, but `datetime.fromtimestamp` raises `OverflowError` for values beyond the platform range.
    Reproduced at seed for `1e30`, `inf`, the 24-digit string and `-1e20`. `nan` raises `ValueError`
    and is already handled.
  - `_parse_exp_date_from_custom_properties` (`:323-328`) calls `.get` on `user_info` without checking
    its type. So do three siblings: `get_account_status` (`:336`), `get_max_connections` (`:344`) and
    `get_active_connections` (`:352`).
  - `save()` re-parses on every save of an XC profile (`:283-304`), so a stored bad value poisons even
    a name-only save. `get_account_expiration` is on the admin list page (`apps/m3u/admin.py:127`).
- **Fix.** Add `OverflowError` to the tuple at `:319`. Add a private `_user_info()` accessor that
  returns the dict or `{}`, and use it at `:327`, `:341`, `:349` and `:357`. `apps/m3u/admin.py:159-163`
  guards with `if user_info:` and would still call `.items()` on a truthy non-dict. That is a separate
  display defect, left alone and noted in the PR description.
- **Tests.** New file `apps/m3u/tests/test_profile_exp_date_out_of_range.py`, with DB-backed XC
  accounts built like `test_profile_exp_date_sync.py`:
  - `test_out_of_range_exp_date_does_not_raise_on_refresh_save` runs `subTest`s for the 24-digit
    string, `"1e30"`, `float("inf")` and `"-1e20"`, each through
    `save(update_fields=["custom_properties", "exp_date"])`, the refresh task's own call. `exp_date`
    must keep its previous value.
  - `test_name_only_save_of_a_row_holding_a_bad_exp_date_succeeds`.
  - `test_get_account_expiration_returns_none_for_out_of_range_exp_date`.
  - `test_non_dict_user_info_does_not_raise` runs `subTest`s for `None`, a list and a string, across
    `save()` and the four accessors.

  `test_profile_exp_date_sync.py` and `test_default_profile_max_streams_signal.py` must stay green
  unmodified. Editing `apps/m3u/models.py` fires the `makemigrations --check` hook. No field changes,
  so it must stay clean.
- **Size** S. **Upstreamable** yes: upstream `dev` has the same tuple at `apps/m3u/models.py:319` and
  the same `.get` at `:328`.

### #171: `$0` in an M3U profile replace pattern injects NUL bytes, and `$01` injects a control byte

- **Root cause.** Four copies of `regex.sub(r'\$(\d+)', r'\\\1', ...)` rewrite `$N` to `\N`.
  `\0` is an octal escape for NUL, and `\01` is `\x01`. The copies are:
  - `apps/m3u/utils.py:22` (`convert_js_numbered_backreferences`, used by the channel rename and
    its preview);
  - `apps/proxy/next_source.py:285` (`transform_url`, used by every live tune and by the WebSocket
    `m3u_profile_test` preview at `dispatcharr/consumers.py:163`);
  - `apps/proxy/vod_proxy/views.py:603` (`_transform_url`);
  - `apps/m3u/tasks.py:3097` (`get_transformed_credentials`).
- **Reproduced at seed.**

  | input | result |
  |---|---|
  | `transform_url("/", r"(.*)$", "$0")` | `'\x00\x00'` |
  | `transform_url("http://h/u/p/1.ts", r"(h)/(u)", "$01/$2")` | `'http://\x01/u/p/1.ts'`. The `$01` variant is found here. It has the same root cause. |
- **Fix.** Change the rule inside `convert_js_numbered_backreferences` to
  `regex.sub(r"\$(\d+)", r"\\g<\1>", replacement)`, so `$N` becomes `\g<N>`, and make the other three
  sites call it for their `$N` step. Each keeps its own `$<name>` line. With this rule `$0` is the
  whole match, which satisfies the issue's own identity property (`transform_url("/", "(.*)$", "$0") ==
  "/"`), and `$01` is group 1. This is **the rule the codebase already uses** at
  `apps/channels/api_views.py:1560` (`translate_js_replacement`). Invalid groups (`$12` on a
  one-group pattern) still raise, exactly as `\12` does today (measured). The rename-parity table at
  `apps/m3u/tests/test_rename_preview_parity.py:42-79` exercises preview and rename through the same
  helper, so parity holds by construction. JavaScript's own reading, a literal `$0`, was considered
  and rejected: see the open questions.
- **Tests.**
  - New file `apps/m3u/tests/test_js_backreference_conversion.py`:
    `test_dollar_zero_is_the_whole_match_not_a_nul_byte`,
    `test_dollar_leading_zero_group_is_the_group_not_an_octal_escape`,
    `test_get_transformed_credentials_dollar_zero_does_not_corrupt_the_url`.
  - Appended to `apps/proxy/tests/test_next_source_edges.py` as class `TransformUrlBackreferenceTests`:
    `test_transform_url_dollar_zero_round_trips_instead_of_injecting_nul_bytes` (the issue's shrunk
    counterexample) and `test_transform_url_dollar_leading_zero_is_group_one`.
  - New file `apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py`:
    `test_vod_transform_dollar_zero_does_not_inject_nul_bytes`.

  Existing tests that must stay green unmodified: the parity table, `TransformUrlNoMatchTests`, and the
  consumer's ReDoS and rewrite tests (`tests/test_websocket_consumer_filter.py:271-340`).
- **Size** S. **Upstreamable** no. `apps/proxy/next_source.py` is fork-only (upstream's copy is
  `apps/proxy/live_proxy/url_utils.py:243`). The `apps/m3u/utils.py:22` hunk would apply unchanged.

### #68: the credential fingerprint uses `.lower()`, so Unicode case variants escape the shared cap

- **Root cause.** `compute_credential_fingerprint` (`apps/m3u/connection_pool.py:49-54`) normalises
  with `username.strip().lower()`. Reproduced at seed with explicit code points:
  `f("\u00b5", "0") != f("\u00b5".upper(), "0")`, because U+00B5 uppercases to U+039C, which
  lowercases to U+03BC. ASCII usernames are unaffected.
- **Fix.** Use `.casefold()`, the Unicode caseless-match normalisation. There are two consequences to
  state in the PR:
  - `ß` and `ss` now group together. Over-grouping two distinct logins tightens the cap, which is the
    safe direction; under-grouping lets the provider's limit be exceeded.
  - The fingerprint changes on deploy for any username where `lower()` differs from `casefold()`.
    Releases use the key stored at reserve time (`_remember_credential_release_key`,
    `:241-244`), so no counter is stranded. In-flight streams finish on the old key and new ones take
    the new key. The fingerprint is not persisted anywhere else (grep: no other non-test reader).
- **Test.** Appended to `apps/m3u/tests/test_connection_pool.py`:
  `test_fingerprint_groups_usernames_that_differ_only_by_unicode_case`, the shrunk counterexample
  `"\u00b5"` against its `.upper()`, plus an ASCII control.
- **Size** S. **Upstreamable** yes: upstream `dev` has the same line at `apps/m3u/connection_pool.py:53`.

### #146: a credential counter below zero is never repaired and silently lifts the cap

- **Root cause.** `_safe_decr` (`apps/m3u/connection_pool.py:232-238`) returns early at `:234` on
  `current <= 0`, leaving a negative key negative. The keys carry no TTL. The cap is effectively lifted
  in the **reserve** path, not only in the read-only gate the issue quotes (`:175`): with the counter at
  `-3` and `max_streams=1`, INCR-first reservation (`:272-277`) admits four streams (`-2`, `-1`, `0`,
  `1`) before refusing the fifth. So repairing only on release, as the issue proposes, leaves the cap
  lifted until the first release.
- **Fix.**
  - In `_safe_decr`, when `current < 0`, `SET` the key to `0` before returning.
  - In `_reserve_server_group_slot_for_profile`, when the INCR result is `< 1`, the counter was
    negative before this reservation, so `SET` it to `1` and treat it as `1`. Appendix C has the hunk.

  Both repairs are GET/SET or INCR/SET pairs, as non-atomic as the existing code. Two reservations
  racing from a negative counter can leave it one short. That is a transient under-count on an already
  drifted counter, and it converges at the next release. An atomic Lua version is out of scope and is
  named as a follow-up. `release_profile_slot`'s per-profile counter (`:318-323`) has the same shape
  but is not this issue. It is noted, not fixed.
- **Tests.** Appended to `apps/m3u/tests/test_connection_pool.py`, using its existing `FakeRedis`:
  - `test_safe_decr_repairs_a_counter_already_below_zero` uses the shrunk counterexample `-1` and the
    issue's `-3`; both must become `0`.
  - `test_negative_credential_counter_does_not_lift_the_cap` sets the counter to `-3` with
    `max_streams=1`. The first `reserve_profile_slot` must succeed and the second must fail with
    `credential_full`.
- **Size** S. **Upstreamable** yes: upstream `dev` has the same early return at
  `apps/m3u/connection_pool.py:241`.

### #242: `extract_year` raises `AttributeError` on a non-string `releaseDate`

- **Root cause.** `apps/vod/tasks.py:1220-1227` calls `date_string.split('-')` outside its
  `except (ValueError, IndexError)`. Reproduced at seed for `2011`, `1` and `[2011]`. The assessor's
  impact correction holds: the per-series `try` at `:807` and `:918` catches it, so one series is lost
  per bad row, not the whole refresh.
- **Fix.** `int(str(date_string).split('-')[0])`. An integer year now yields that year, which is
  useful because XC panels send `"releaseDate": 2011`. A float, list or bool yields `None` through the
  existing `ValueError` path.
- **Tests.** New file `apps/vod/tests/test_extract_year_non_string.py`:
  `test_integer_release_date_yields_the_year_instead_of_raising` (`2011` gives `2011`),
  `test_shrunk_counterexample_one_does_not_raise` (`1` gives `1`, the same as the string `"1"` today),
  and `test_non_scalar_release_date_is_no_year_not_attribute_error` (`[2011]`, `2011.5` and `True` each
  give `None`).
- **Size** S. **Upstreamable** yes: upstream `dev` has the same body at `apps/vod/tasks.py:1195`.

### #191: PostgreSQL-only migrations stop `TEST_USE_SQLITE=1` from creating a test database

- **Root cause, wider than the issue.** `apps/channels/migrations/0038_add_catchup_fields.py:6-28` and
  `:31-46` run raw PostgreSQL SQL with no vendor guard. **Measured at seed:** with only 0038 guarded,
  SQLite test-DB creation then fails at the next PostgreSQL-only migration,
  `apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py`. That file has a `DO $$`
  PL/pgSQL `RunSQL` at `:205-245`, then `UPDATE vod_movie m SET ... FROM` (an aliased UPDATE, which
  SQLite rejects) in `migrate_vod_logos_forward` (`:7-66`), plus a cleanup at `:149-178`. With both
  files guarded, `TEST_USE_SQLITE=1 manage.py test apps.timeshift.tests.test_helpers` ran 58 tests, OK,
  exit 0. That prototype was reverted and is not committed. The other raw-SQL migrations
  (`channels/0037`, `epg/0025`, `vod/0005`) are already vendor-guarded or passed.
- **Fix.**
  - 0038: add `if schema_editor.connection.vendor != "postgresql": return` to both `RunPython`
    functions.
  - vod 0003: add the same guard to `migrate_vod_logos_forward` and `cleanup_migrated_logos`, and
    replace the `RunSQL` with a `RunPython` that executes the same two statements only on PostgreSQL.
    Appendix D has the shape.

  On PostgreSQL both migrations execute the same SQL as before. A fresh SQLite test database has no
  rows to backfill.
- **Test.** New file `tests/test_migrations_apply_on_sqlite.py`, class `SqliteMigrationGraphTests
  (SimpleTestCase)`, `test_full_migration_graph_applies_on_sqlite`. It runs
  `subprocess.run([sys.executable, "manage.py", "migrate", "--noinput", "-v0"], env={... ,
  "TEST_USE_SQLITE": "1", "DJANGO_SETTINGS_MODULE": "dispatcharr.settings_test"}, cwd=settings.BASE_DIR)`
  and asserts return code 0, with the stderr tail in the failure message. Measured at 2.4 s. The
  database is `:memory:`, so nothing is written, and it works on the read-only `/repo` mount.
- **Routing note.** A future PostgreSQL-only migration under `apps/<app>/migrations/` routes to that
  app's label, not `tests`, so this test would not run on that PR. It runs on shared-path changes and on
  the PR that adds it (the `tests/` file routes to `tests`). Closing that gap needs a `_PATH_ALIASES`
  entry for a glob prefix that `labels_for_changed_paths` does not support. That is not attempted here
  and is listed under open questions.
- **Size** S. **Upstreamable** yes: neither migration carries a vendor guard in upstream `dev`.

---

## PR sections, in implementation order

Every PR: branch off the current `main`, run the named labels in a private container (constraint 6),
run once without `--keepdb`, and open as a **draft**. No PR changes an existing test.

### PR C-1: `fix/C-1-output-input-crashes`

- **Closes** #91 (with #212) and #90 (with #211).
- **Files** `apps/output/views.py`, `apps/output/epg.py`, two new test modules.
- **Labels** `apps.output.tests`.
- **Tasks.**
  1. Write `test_xc_epg_limit_guard.py`. Run it; both tests must ERROR at seed with
     `ValueError: invalid literal for int()` and Django's negative-slice refusal.
  2. Guard the `limit` parse at `views.py:881`. Green.
     **Break-check:** drop the `limit < 0` fallback, and the negative-limit test must redden on the
     negative-slice error.
  3. Write `test_custom_dummy_out_of_range_capture.py`. At seed each subTest must raise the exception
     in #90's table, and the export test must fail on a truncated body.
  4. Add the time and date range checks in `epg.py` (`:452-458`, `:506`). Green.
     **Break-checks:** (a) remove `0 <= minute <= 59`, and the minute test must redden with
     `minute must be in 0..59`; (b) restore `1 <= day <= 31`, and the calendar-date test must redden
     with `day is out of range for month`.
  5. Run `apps.output.tests` whole.
- **Category-I seam.** #210, #162 and #92 will add a "a matched channel name never raises" property
  over `generate_custom_dummy_programs`. It should carry C-1's counterexamples as `@example`s and cite
  this module rather than re-pin them.
- **Upstreamable** partly (the views hunk yes, the epg hunk needs a port).
- **PR description draft.**

  > **fix(output): guard XC `limit` and range-check dummy-EPG captures (#91, #90)**
  >
  > `player_api.php?action=get_short_epg` returned 500 for `limit=abc` or `limit=-5`; both now fall
  > back to 4, like `days`. A channel name whose captured minute, hour, day or year is out of range
  > (`10:75`, `2/31`, `13:30pm`, year 0) raised inside the streamed `/output/epg` generator and cut the
  > file off for every client; the capture is now treated as "no time/date", exactly as an
  > unparseable one already is. Closes #91 (dup #212) and #90 (dup #211).
  > Break-checks: <paste the two failure lines>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-2: `fix/C-2-epg-xmltv-input`

- **Closes** #76 (with #156), #75 and #157.
- **Files** `apps/epg/tasks.py`, two new test modules.
- **Labels** `apps.epg.tests`.
- **Tasks.**
  1. Write `test_malformed_xmltv_timestamp.py`. At seed the three #76 tests must raise `ValueError`
     (the offset check). The two adjacent-offset tests must fail with hour 18 against 13, and 18:30 on
     the 28th against 02:30 on the 29th.
  2. Wrap `:3211-3212` and `:3304-3305`. Green for #76.
     **Break-check:** unwrap `:3304-3305` only; the interleaved-scan test alone must redden with the
     offset `ValueError`.
  3. Add the adjacent-offset normalisation before `:2516`. Green for #75.
     **Break-check:** normalise only on `+`; the `-0800` test alone must redden.
  4. Write `test_channel_id_entity_parity.py`. At seed the four divergent subTests must fail with the
     values in the #157 table, and the two lookup tests must return `None`.
  5. Apply Appendix A. Green.
     **Break-check:** pass `entity_doctype=True` unconditionally in `build_programme_index`; the
     own-DOCTYPE subTest and lookup test must redden with `'aéb' != 'ab'`.
  6. Run `apps.epg.tests` whole. `test_programme_index.py` and `test_entity_resolution.py` must pass
     unmodified.
- **Category-I seam.** #274, #158 and #202 cover `parse_xmltv_time` and `_decode_channel_id`.
  Two properties become true after C-2 and are I's to write: "the spaced and adjacent offset forms parse
  to the same instant", and "`_decode_channel_id` equals lxml over `name2codepoint` plus HTML5 names,
  with and without an own DOCTYPE". I must not change `parse_xmltv_time`'s raising contract.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(epg): skip malformed programme timestamps in the offset lookup, honour unspaced offsets, and key the programme index the way lxml reads channel ids (#76, #75, #157)**
  >
  > One `<programme start="... +2400">` 500'd `POST /api/epg/programs/current/` for every channel in
  > the request; the offset helpers now skip it as the bulk parser already does. `20260728183000+0530`
  > was stored as UTC; the missing space is now inserted before parsing. The byte-offset index decoded
  > `channel=` with `html.unescape` while the database holds lxml's value; they disagreed for HTML5-only
  > entities, for HTML 4 entities in files that carry their own DOCTYPE, for literal tabs and for
  > semicolon-less entities. The index now asks lxml, under the same DOCTYPE decision as the import,
  > with a fast path for ids that need no decoding.
  > Closes #76 (dup #156), #75, #157. Break-checks: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-3: `fix/C-3-m3u-provider-input`

- **Closes** #262, #217 and #199.
- **Files** `apps/m3u/tasks.py`, `apps/m3u/models.py`, `apps/m3u/utils.py`, `apps/m3u/tests/test_stream_filters.py`
  (appended class only), three new test modules.
- **Labels** `apps.m3u.tests`.
- **Tasks.**
  1. #262: append `StreamFilterRegexTimeoutTests`. At seed the nested-quantifier test must fail on
     the elapsed bound; stdlib `re` needs several seconds against a 2 s bound.
  2. Add `M3U_FILTER_REGEX_TIMEOUT` and `_BoundedFilterPattern`, switch to `regex`, and bound
     `applies_to`. Green.
     **Break-check:** delete `self.tripped = True`; the warned-once test must redden with three
     WARNING records, not one.
  3. #217: write `test_non_utf8_playlist.py`. At seed the decode tests must raise
     `UnicodeDecodeError ... 0xe9`, and the lock test must fail on `acquire_task_lock` returning `False`.
  4. Register the error handler and apply it at the four decode sites. Split `refresh_m3u_groups`
     per Appendix B. Green.
     **Break-checks:** (a) `errors="strict"` at `:175` only; the `.m3u` subTest alone must redden;
     (b) remove the `finally`'s `release_task_lock`; the lock test must redden.
  5. #199: write `test_profile_exp_date_out_of_range.py`. At seed it must raise `OverflowError` and
     `AttributeError`.
  6. Add `OverflowError` and the `_user_info()` accessor. Green.
     **Break-check:** remove `OverflowError`; the four refresh-save subTests must redden with
     `timestamp out of range for platform time_t`.
  7. Run `apps.m3u.tests` whole. Among the tests that must stay green are all of `test_stream_filters.py`,
     `test_xz_playlist.py`, `test_refresh_db_recovery.py`, `test_profile_exp_date_sync.py` and
     `test_rename_preview_parity.py`.
- **Category-I seam.** #145 (stream filters) must not assert timing on generated patterns and must
  treat a timed-out filter as non-matching. #200 (exp_date) can assert totality over all JSON scalars
  after C-3. #218 and #69 (M3U parsing) can generate arbitrary bytes into `_open_m3u_text_source`
  after C-3, where today they would have to restrict to UTF-8.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(m3u): bound stream-filter regexes, decode non-UTF-8 playlists, release the group-refresh lock on every exit, and survive out-of-range `exp_date` (#262, #217, #199)**
  >
  > Stream filters now run on the `regex` engine with the same 0.1 s timeout the rename path uses; a
  > filter that times out is logged once and treated as non-matching for the rest of that refresh
  > (fail-open, as rename already is). Playlist bytes that are not valid UTF-8 are decoded as cp1252
  > instead of raising — on the ZIP path the issue names and on the plain/.gz/.xz/URL path it does not,
  > which crashed the same way. `refresh_m3u_groups` now releases its lock and stops its renewer in a
  > `finally`; before, an escaped exception left the renewer extending the lock for the worker's life.
  > `exp_date` values past the platform's time range and non-dict `user_info` no longer raise from
  > `save()` or the admin list.
  > Closes #262, #217, #199. Break-checks: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-4: `fix/C-4-js-backreference-rewrite`

- **Closes** #171.
- **Files** `apps/m3u/utils.py`, `apps/m3u/tasks.py` (`:3097`), `apps/proxy/next_source.py` (`:285`, plus
  one import), `apps/proxy/vod_proxy/views.py` (`:603`), two new test modules, and one class appended
  to `apps/proxy/tests/test_next_source_edges.py`.
- **Labels** `apps.m3u.tests`, `apps.proxy.tests`, `apps.proxy.vod_proxy.tests`. That is three labels
  where the lead prefers two. Splitting would leave copies of the same rule disagreeing between merges,
  and the single-helper design exists to prevent exactly that, so all four sites land together.
- **Gate 2.** `apps/proxy/next_source.py` is listed in `scripts/coverage_live_path.coveragerc:44`. Run
  `scripts/coverage_live_path_isolated.sh` before pushing. The edit adds one import statement and
  replaces one statement, so `missing` must not move. If it does, STOP. A green label run does not imply
  a green gate.
- **Tasks.**
  1. Write the tests. At seed `$0` must yield NUL bytes and `$01` a `\x01`, in all four places.
  2. Change the helper's rule to `\g<N>` and point the three sites at it. Green.
     **Break-check:** revert only `apps/proxy/vod_proxy/views.py:603` to the inline `\\\1` form; the
     VOD test alone must redden with `'\x00' in result`.
  3. Run the three labels plus `tests` (for `test_websocket_consumer_filter.py`, which exercises
     `transform_url` through the preview), then the isolated coverage script.
- **Category-I seam.** The issue's Hypothesis identity property (`transform_url(target, "(.*)$", "$0")
  == target`) belongs to I and becomes true after C-4.
- **Upstreamable** no. The `apps/m3u/utils.py` hunk alone would apply.
- **PR description draft.**

  > **fix(m3u,proxy): `$N` backreferences become `\g<N>` everywhere, so `$0` is the whole match rather than a NUL byte (#171)**
  >
  > Four copies of the JS-to-Python replacement rewrite turned `$0` into `\0` (NUL) and `$01` into
  > `\x01`, silently corrupting stream URLs, VOD URLs, XC credentials and channel renames. One helper
  > now does the rewrite, using the rule `apps/channels/api_views.py` already used; invalid group
  > numbers still fail exactly as before.
  > Gate 2: `coverage_live_path_isolated.sh` <paste result>. Closes #171. Break-check: <paste>. No existing
  > test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-5: `fix/C-5-credential-pool-counters`

- **Closes** #68 and #146.
- **Files** `apps/m3u/connection_pool.py`, and classes appended to `apps/m3u/tests/test_connection_pool.py`.
- **Labels** `apps.m3u.tests`.
- **Tasks.**
  1. Write the three tests. At seed each must fail: `False` for the fingerprint, `-1 != 0` for the
     counter, and the second reservation succeeding.
  2. Switch to `.casefold()` and apply Appendix C. Green.
     **Break-checks:** (a) keep the `_safe_decr` repair but drop the reserve repair; the cap test alone
     must redden, which proves the release-side repair alone is insufficient; (b) revert to `.lower()`;
     the fingerprint test must redden.
  3. Run `apps.m3u.tests` whole. Every existing test in `test_connection_pool.py` must pass unmodified.
- **Category-I seam.** #145 owns the "never below zero" and "case variants share a fingerprint"
  properties, which become true after C-5.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(m3u): casefold credential fingerprints and repair negative credential counters (#68, #146)**
  >
  > `.lower()` is not a caseless match (`µ` and its uppercase fingerprinted differently), so the same
  > login escaped its shared cap; it is now `.casefold()` — note `ß`/`ss` now group, the conservative
  > direction. A credential counter that had drifted below zero stayed there and admitted streams past
  > `max_streams`; release now clamps it to 0 and reservation repairs it to 1. Both repairs are as
  > non-atomic as the code around them; a Lua version is a follow-up.
  > Closes #68, #146. Break-checks: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-6: `fix/C-6-vod-extract-year`

- **Closes** #242.
- **Files** `apps/vod/tasks.py`, one new test module.
- **Labels** `apps.vod.tests`, `apps.output.tests` (routing via `_PATH_ALIASES`).
- **Tasks.**
  1. Write the test. At seed it must raise `AttributeError: 'int' object has no attribute 'split'`.
  2. Apply the `str()` coercion. Green.
     **Break-check:** coerce only `int`; the list subTest must redden with `AttributeError`.
  3. Run both labels.
- **Category-I seam.** #243 widens its `extract_year` strategy from strings to arbitrary JSON values
  once C-6 merges. The sweep already records that ordering.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(vod): `extract_year` accepts non-string provider dates (#242)**
  >
  > A provider sending `"releaseDate": 2011` raised `AttributeError` and that series was skipped with an
  > ERROR log; the value is now coerced to text first, so an integer year yields the year and other
  > shapes yield no year. Closes #242. Break-check: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

### PR C-7: `fix/C-7-sqlite-migrations`

- **Closes** #191.
- **Files** `apps/channels/migrations/0038_add_catchup_fields.py`,
  `apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py`, and the new
  `tests/test_migrations_apply_on_sqlite.py`.
- **Labels** `apps.channels.tests`, `apps.vod.tests`, `apps.output.tests` and `tests`. That is four,
  because two apps' migrations are involved. Each label is cheap, and the new test only runs if `tests`
  is selected, which the new file guarantees.
- **Tasks.**
  1. Write the test. At seed it must fail with `near "~": syntax error` naming 0038.
  2. Guard 0038 only. The test must now fail with `near "DO": syntax error` in vod 0003. This is the
     measured intermediate state; record it.
  3. Apply Appendix D. Green.
     **Break-check:** remove the guard from `cleanup_migrated_logos` only; the test must redden in vod
     0003.
  4. Run the four labels on PostgreSQL. The backfills must still execute there. Also run
     `TEST_USE_SQLITE=1 manage.py test apps.timeshift.tests.test_helpers` once and paste the result:
     58 tests OK was measured on the prototype.
- **Upstreamable** yes.
- **PR description draft.**

  > **fix(migrations): vendor-guard the two PostgreSQL-only migrations so `TEST_USE_SQLITE=1` can build a test database (#191)**
  >
  > `channels/0038` and — found while fixing it — `vod/0003` run raw PostgreSQL SQL (`~`, `->>`,
  > `DO $$`, aliased `UPDATE … FROM`). Both now skip their data steps off PostgreSQL, where a fresh test
  > database has nothing to migrate; on PostgreSQL they run the same SQL as before. A new test applies
  > the whole migration graph on in-memory SQLite (~2.4 s). This is what the gh-aw fuzz and remediation
  > sandboxes need to run DB-backed tests at all.
  > Closes #191. Break-check: <paste>. No existing test changed.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Decision memos

None. No rule-4 policy item (#82, #94, #16, #277, #109, #133) is in category C.

---

## Coverage table

| issue | disposition | PR section |
|---|---|---|
| 262 | fix | C-3 |
| 217 | fix | C-3 |
| 199 | fix | C-3 |
| 171 | fix | C-4 |
| 212 | duplicate of #91; closed by the same change | C-1 |
| 91 | fix | C-1 |
| 211 | recommended duplicate of #90; closed by the same change either way | C-1 |
| 90 | fix | C-1 |
| 156 | duplicate of #76; closed by the same change | C-2 |
| 76 | fix | C-2 |
| 75 | fix | C-2 |
| 157 | fix (scope wider than the assessor's correction) | C-2 |
| 242 | fix (assessor's p1-to-p3 downgrade holds) | C-6 |
| 68 | fix | C-5 |
| 146 | fix | C-5 |
| 191 | fix (scope includes vod/0003) | C-7 |

---

## Open questions for the user

Each has a default that this plan already adopts; answer only to override it.

1. **#217 decoding policy.** Default: invalid UTF-8 byte runs are decoded as cp1252, so a Latin-1
   playlist imports with correct names. The alternatives are `errors="replace"` (imports, with `�` in
   names) or rejecting the playlist with the account set to ERROR (the issue's first suggestion). The
   code shape is the same for all three; only user-visible behaviour differs.
2. **#171 meaning of `$0`.** Default: the whole match (`\g<0>`), matching the issue's own identity
   property and `apps/channels/api_views.py:1560`. The alternative is JavaScript's reading, a literal
   `$0`. That is JS-faithful, but nothing in this codebase evaluates these patterns in JavaScript: the
   preview is server-side (`dispatcharr/consumers.py:163`).
3. **#191 routing gap.** Should a follow-up teach `labels_for_changed_paths` to send any
   `apps/*/migrations/` change to the `tests` label as well, so the new SQLite migration test runs on the
   PR that adds a PostgreSQL-only migration? Not part of this plan.

Follow-ups noted, not planned: an atomic Lua `_safe_decr` and reserve; the same negative-counter
shape in `release_profile_slot`; `apps/m3u/admin.py:159-163` iterating a non-dict `user_info`;
`parse_xmltv_time`'s traceback-per-failure ERROR log on a polled path; and `_transform_url` in
`apps/proxy/vod_proxy/views.py` still calling `regex.sub` with no timeout. None of these is a tracked
issue in this category.

---

## Appendix A: C-2, `_decode_channel_id` parity (against `a54b09a9`)

```diff
@@ apps/epg/tasks.py  _open_xmltv_file (:290)
+def _xmltv_file_gets_entity_doctype(file_path: str) -> bool:
+    """True when _open_xmltv_file will prepend _HTML_ENTITY_DOCTYPE, i.e. the
+    file does not declare its own DOCTYPE in its first 512 bytes."""
+    with open(file_path, 'rb') as f:
+        start = f.read(512)
+    return not (b'<!DOCTYPE' in start or b'<!doctype' in start.lower())
+
+
 def _open_xmltv_file(file_path: str):
@@
     f = open(file_path, 'rb')
     start = f.read(512)
-
-    # Do not inject if the file already declares a DOCTYPE.
-    if b'<!DOCTYPE' in start or b'<!doctype' in start.lower():
+    # Do not inject if the file already declares a DOCTYPE (same test as
+    # _xmltv_file_gets_entity_doctype, which the byte-offset index uses).
+    if b'<!DOCTYPE' in start or b'<!doctype' in start.lower():
         f.seek(0)
         return f
@@ apps/epg/tasks.py  (:2902)
-def _decode_channel_id(raw):
-    """Match how EPGData.tvg_id is stored: resolve XML entities and strip, so byte-level index keys equal the lxml-parsed channel ids."""
-    s = raw.decode('utf-8', errors='replace')
-    if '&' in s:
-        s = html.unescape(s)
-    return s.strip()
+_NEEDS_LXML_DECODE = (b'&', b'\t', b'\n', b'\r')
+
+
+@functools.lru_cache(maxsize=4096)
+def _decode_channel_id(raw, quote=b'"', entity_doctype=True):
+    """Return the channel id exactly as lxml's recover-mode iterparse reads it
+    (entity resolution under the same DOCTYPE decision as _open_xmltv_file,
+    attribute-value whitespace normalisation), stripped -- so byte-level index
+    keys equal EPGData.tvg_id. Ids with no entity or whitespace escape take a
+    fast path."""
+    if not any(b in raw for b in _NEEDS_LXML_DECODE):
+        return raw.decode('utf-8', errors='replace').strip()
+    prefix = _HTML_ENTITY_DOCTYPE if entity_doctype else b''
+    elem = etree.fromstring(
+        prefix + b'<p c=' + quote + raw + quote + b'/>',
+        etree.XMLParser(recover=True, remove_blank_text=True),
+    )
+    value = elem.get('c') if elem is not None else None
+    return (value or '').strip()
```

At each of the three call sites (`:3007`, `:3184`, `:3277`) compute
`entity_doctype = _xmltv_file_gets_entity_doctype(file_path)` once, before the read loop, and call
`_decode_channel_id(m.group(1), b'"', entity_doctype) if m.group(1) is not None else
_decode_channel_id(m.group(2), b"'", entity_doctype)`. Add `import functools`, which is absent at the
seed. The cache needs hashable arguments. `m.group()` on the `bytearray` buffer already returns
`bytes`, which was checked at the seed, so no wrapping is needed.

## Appendix B: C-3, `refresh_m3u_groups` split (against `a54b09a9`)

```diff
@@ apps/m3u/tasks.py (:1544)
 @shared_task
 def refresh_m3u_groups(account_id, use_cache=False, full_refresh=False, scan_start_time=None):
-    """Refresh M3U groups for an account.
-    ...
-    """
+    """Refresh M3U groups for an account. (docstring unchanged)"""
     if not acquire_task_lock("refresh_m3u_account_groups", account_id):
         return f"Task already running for account_id={account_id}.", None

     lock_renewer = TaskLockRenewer("refresh_m3u_account_groups", account_id)
     lock_renewer.start()
+    try:
+        return _refresh_m3u_groups_locked(
+            account_id, use_cache, full_refresh, scan_start_time
+        )
+    finally:
+        # Every exit, including an unexpected exception, stops the renewer and
+        # releases the lock -- mirrors refresh_single_m3u_account.
+        lock_renewer.stop()
+        release_task_lock("refresh_m3u_account_groups", account_id)
+
 
+def _refresh_m3u_groups_locked(account_id, use_cache, full_refresh, scan_start_time):
+    """Body of refresh_m3u_groups; runs with the group-refresh lock held."""
     try:
         account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)
     except M3UAccount.DoesNotExist:
-        lock_renewer.stop()
-        release_task_lock("refresh_m3u_account_groups", account_id)
         return f"M3UAccount with ID={account_id} not found or inactive.", None
```

Delete the same two lines at the other eight sites (`:1595-1596`, `:1608-1609`, `:1680-1681`,
`:1719-1720`, `:1736-1737`, `:1748-1749`, `:1755-1756`, `:1820-1821`). After the edit,
`grep -c 'release_task_lock("refresh_m3u_account_groups"' apps/m3u/tasks.py` must print `1`. The body
reads no other name from the outer scope. Confirm with a grep for `lock_renewer` inside the new
function, which must print `0` (it exits 1 on zero matches, so run it bare, per constraint 2).

## Appendix C: C-5, counter repair (against `a54b09a9`)

```diff
@@ apps/m3u/connection_pool.py (:232)
 def _safe_decr(redis_client, key: str) -> None:
     current = int(redis_client.get(key) or 0)
     if current <= 0:
+        if current < 0:
+            # A drifted-negative counter (no TTL) would otherwise stay negative
+            # and admit streams past max_streams; repair it on sight.
+            redis_client.set(key, 0)
         return
@@ apps/m3u/connection_pool.py (:272)
     cred_count = redis_client.incr(cred_key)
+    if cred_count < 1:
+        # The counter was negative before this reservation; count this stream
+        # once and discard the drift so the cap applies from here on.
+        redis_client.set(cred_key, 1)
+        cred_count = 1
     if cred_count <= profile.max_streams:
         return True, cred_key
```

## Appendix D: C-7, vod 0003 (against `a54b09a9`)

```diff
@@ apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py
 def migrate_vod_logos_forward(apps, schema_editor):
+    if schema_editor.connection.vendor != 'postgresql':
+        return  # PostgreSQL-only SQL; a fresh non-PG (test) database has no rows
@@
 def cleanup_migrated_logos(apps, schema_editor):
+    if schema_editor.connection.vendor != 'postgresql':
+        return
@@
+_DROP_LOGO_FK_SQL = (
+    """<the first DO $$ ... $$; block, verbatim from :208-222>""",
+    """<the second DO $$ ... $$; block, verbatim from :224-237>""",
+)
+
+
+def drop_logo_fk_constraints(apps, schema_editor):
+    if schema_editor.connection.vendor != 'postgresql':
+        return
+    for statement in _DROP_LOGO_FK_SQL:
+        schema_editor.execute(statement)
+
+
 class Migration(migrations.Migration):
@@
-        migrations.RunSQL(
-            sql=[ <two DO blocks> ],
-            reverse_sql=[
-                migrations.RunSQL.noop,
-            ],
-        ),
+        migrations.RunPython(drop_logo_fk_constraints, migrations.RunPython.noop),
```

The two SQL strings move byte-for-byte. Verify with
`git show "a54b09a9:apps/vod/migrations/0003_vodlogo_alter_movie_logo_alter_series_logo.py"` and a diff
of the extracted strings. `schema_editor.execute` is what `RunSQL` itself calls, so PostgreSQL runs the
identical statements in the identical transaction. The only observable difference is `sqlmigrate`
output, which now shows a Python operation. `migrate_vod_logos_forward` uses the module-level
`django.db.connection`, not `schema_editor.connection`. The guard reads `schema_editor.connection`,
which is the same connection under the default database.
