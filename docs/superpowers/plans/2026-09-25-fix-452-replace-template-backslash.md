# Fix plan, #452 — a backslash in an M3U replace template is literal text, by ruling

> **For agentic workers:** implement this plan with a `sonnet` implementer, escalate a stuck one to
> `opus`, and have a `fable` (or `opus`) reviewer pass the PR against this plan before it lands, per
> CLAUDE.md § Delegation for phase work. Task steps are numbered; tick them off in the PR description.

**Goal.** Close the half of #171 that #440 left open. #440 made `$0`/`$01` safe by adopting JavaScript's
`$n` grammar for the *dollar* tokens, but every replace template still reaches Python's regex
replacement-template parser with its backslashes intact, so `\0` puts a NUL byte into a stream URL,
`\x01` a control byte and `\n` a newline, where the SPA's own preview (`String.prototype.replace`)
shows the operator literal text. The issue asks for a **grammar ruling** before a patch. This plan
makes the ruling (§ The ruling, with a default the user can override), then fixes all five paths
through one helper so the SPA preview, the WebSocket preview and the live transform agree on
backslashes exactly as they now agree on `$n`, widens the category-I property test that was
deliberately holding its alphabet back for this ruling, and records the decision as an ADR.

**Seed SHA: `36e4ce10b164c6cf978bb9fa12be66dbae6ba982`** (`main`, 2026-09-25, the merge of #492). Every
`file:line` below was opened there; every measurement in § Measured at seed was run there inside the
shared test container (`dispatcharr-testrunner`, bind-mounted at `/Users/dion/git/Dispatcharr`, which
was at that SHA) with Python 3.13.15 and `regex` 2026.7.19, and the JavaScript column against Node
22.14.0. Line numbers drift; the anchors are the code shapes quoted beside them.

**Issue.** [#452](https://github.com/D10Scot/Dispatcharr/issues/452), filed from the opus review of
#440 (findings F1–F3, `scratchpad/impl/review-C-4-r1.md`). Predecessors: #440 (fixplan C, PR C-4,
`docs/superpowers/plans/2026-09-23-fixplan-C-input-crashes.md` § #171) and #455 (fixplan I, the M3U
property tests, whose `apps/m3u/tests/test_property_backreferences.py` excludes the backslash from its
template alphabet "until #452 is ruled").

**Architecture.** Django 6 + DRF control plane. The five paths are all Django-side Python: three URL
transforms (every live tune, every VOD tune, the XC credential transform) and two channel-name
transforms (the auto-sync rename and its server-side preview). The Go relay never sees a template — it
receives the transformed URL on the `next-source` answer — and is untouched.

**Tech stack.** Python 3.13, Django 6, the third-party `regex` module (already the engine at all five
sites; its replacement-template grammar is stdlib `re`'s), Hypothesis (already a main dependency).

**Planner's worktree.** `.worktrees/plan-452-baseline`, branch `plan/452-replace-template-backslash`.
Only this file is committed there.

**Implementer's branch.** `fix/452-replace-template-backslash`, off `main` at or after the seed, in its
own worktree. It does not take the `migration/` prefix: no file under `docker/`, `relay/` or
`docker/nginx.conf` is touched.

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
4. **Test-modification rule.** A test may change only when the behaviour it pins is the thing being
   changed, and every such change is listed in the PR section with its before and after. Never widen
   a tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new
   test named after the defect. **Exactly one existing test module changes in this plan**, the
   category-I property module, and only in the way § Task 4 lists; it was written to be widened here.
5. **Break-check every new test.** Each task names one deliberate wrong edit. Make it, run the new
   test, confirm it fails *with a message naming the mechanism* (not an import error or a side effect
   of the edit), revert, confirm green. Record the failure line in the PR description.
6. **Test container.** Hooks always use the shared container `dispatcharr-testrunner`, whose mount
   decides which tree is tested (`CLAUDE.md` § Test hooks). Re-point it at your worktree only after the
   occupancy check (`docker ps --filter name=dispatcharr-testrunner` plus mtimes); for runs you launch
   yourself prefer a private container:
   `DISPATCHARR_TEST_CONTAINER=fix-452 DISPATCHARR_TEST_DB_VOLUME=fix-452-db CLAUDE_HOOK_REPO_ROOT=<wt> .claude/hooks/start-test-container.sh`,
   then `docker exec -w /repo -e DJANGO_SECRET_KEY=hook-test-secret fix-452 python manage.py test --keepdb <label>`.
   **Every `manage.py` exec must carry `-e DJANGO_SECRET_KEY=hook-test-secret`** (the container bakes
   none in, and `manage.py check` and `manage.py test` both die with `The SECRET_KEY setting must not
   be empty.` without it — measured at seed; `scripts/coverage_live_path_isolated.sh:18-23` records
   the same rule and `.claude/hooks/run-affected-tests.sh:121` is where the hook supplies it).
   Run one label at a time and **once without `--keepdb`** before push (the seeded-row drift trap;
   the #440 review reproduced the `--keepdb` ledger artefact on exactly this label pair).
7. **Gate 2.** `apps/proxy/next_source.py` is in `scripts/coverage_live_path.coveragerc:44`. Run
   `scripts/coverage_live_path_isolated.sh --gate` before pushing. `missing` must not move; if it
   does, STOP and report. A green label run does not imply a green gate.
8. **No `metrics/curated/` edits.** Neither #452 nor #171 has a `defects.yml` entry (checked at seed:
   `grep -nE 'issue: (452|171)[,}]' metrics/curated/defects.yml` is empty), neither is a CLAUDE.md
   "Known defects" bullet, and neither has an e2e `test.fail()` pin or a parity-matrix row. A PR that
   discovers otherwise STOPs and reports.
9. **No frontend edit.** The SPA's two previews already implement the ruling (they *are*
   `String.prototype.replace`); the UI copy already says "Use $1, $2, etc." and nothing about
   backslashes. Touching `frontend/` would put the whole 6,134-test suite on the commit gate for a
   sentence. Recorded as a follow-up.
10. **The sixth site stays out.** `translate_js_replacement` in `apps/channels/api_views.py:1552-1561`
    (the bulk channel rename) has its own rewrite, was excluded from #171 by name, and has the same
    backslash hole. It is a follow-up to *file*, not to fix here (§ Follow-ups).

---

## The ruling

The issue offers two grammars. This plan adopts **(a)** and is executable as written for it; **(b)** is
described to the depth needed to see its cost, and choosing it means re-issuing this plan, not
adapting a step.

### (a) Default: JavaScript's replacement grammar, in full. A backslash is literal text.

The substitution tokens are `$n` (`1`–`9`), `$nn` (`01`–`99`) and `$<name>`, exactly as #440 left
them. **Every other character, the backslash included, is literal.** `\0` is the two characters `\`
and `0`; `\1` is not a backreference; `\n` is not a newline.

Grounds:

1. **It is what the operator is shown.** The M3U-profile modal renders the template through
   `applyRegex` (`frontend/src/utils/forms/M3uProfileUtils.js:34-41`, `input.replace(new RegExp(pattern, 'g'), replacer)`),
   and the field's own description reads "Use $1, $2, etc. to reference regex capture groups"
   (`frontend/src/components/forms/M3UProfile.jsx:309` and `:369`). In JavaScript a backslash in a replacement
   string is literal. Under (a) the three previews of the same template — the SPA's local one, the
   WebSocket `m3u_profile_test` one (`dispatcharr/consumers.py:163`, which calls `transform_url`) and
   the live tune — agree on every template, which is the property #440 bought for `$n` and this plan
   completes.
2. **XC "simple" mode writes a password verbatim into the template.** `applyXcSimplePatterns`
   (`M3uProfileUtils.js:138-149`) sets `replace_pattern` to `<newUsername>/<newPassword>`. A password
   containing a backslash is corrupted today with no error anywhere the operator can see: `p\0ss`
   puts a NUL into the credential, `p\1ss` substitutes group 1 or raises `invalid group reference`
   and `get_transformed_credentials` silently falls back to the *base* credentials, so the profile
   does nothing. Under (a) the password round-trips. No validation rule under (b) can rescue this
   case, because the operator never typed a template.
3. **One function, no validation surface.** (a) is a single string operation at the point of use
   (Appendix A). (b) needs a validator at every write path — the profile serializer, the group
   `custom_properties` writer that carries `name_replace_pattern`, and the WebSocket preview, which
   takes raw text — *and* a guard at the point of use anyway, because rows at rest predate any
   validator, *and* a definition of "dangerous escape" that tracks Python's template grammar
   (`\a \b \f \n \r \t \v \0 \x \u \U \N`, plus every unknown escape, which raises) rather than a
   fixed list.
4. **It closes review finding F3 for free.** A literal `\g<name>` naming a group the pattern lacks
   raises `IndexError` (measured, § Measured at seed), which the rename sync catches nowhere
   (`apps/m3u/tasks.py:2638` catches `(regex.error, TimeoutError)`; the per-stream `except Exception`
   at `:2790` then counts the stream as failed) and the rename preview catches nowhere
   (`apps/channels/api_views.py:434`, `(TimeoutError, re.error)`). Under (a) no backslash reaches the
   parser, so `\g<...>` cannot be typed into existence on either rename path. The URL sites already
   catch `Exception`.

Cost, and the migration note the issue asks for: **an operator relying on Python-style `\1` today
loses it and must write `$1`.** This population exists in principle — the upstream project's rewrite
was the pre-#440 `\$(\d+) → \1` on the same Python parser, so a template written as `\1` worked there
and worked here until this PR — but nothing in either UI ever documented it. The PR description
carries the audit query (§ PR section) so the maintainer can check the instance before deploying;
§ Ruling 2 covers whether to rewrite such rows automatically.

### (b) Alternative: document the hybrid grammar and validate away the dangerous escapes

Keep `\1`–`\99` and `\g<...>` as Python backreferences, reject `\0`, `\x`, `\u`, `\U`, `\N` (and, to be
complete, `\a \b \f \n \r \t \v` and a trailing lone backslash) at validation time. Not planned in
detail. What it would need, so its size is visible: a `validate_replace_pattern` on
`M3UAccountProfileSerializer` (`apps/m3u/serializers.py:74-92`); the same on whichever serializer
writes `ChannelGroupM3UAccount.custom_properties["name_replace_pattern"]`; a refusal in
`dispatcharr/consumers.py`'s `m3u_profile_test` branch; a point-of-use guard in the helper for rows at
rest; a documented grammar in the two UI descriptions and in the helper docstring; and it leaves
grounds 2 above unfixed and F3 open — `IndexError` is not a `regex.error` subclass, so both rename
`except` clauses (`tasks.py:2638`, `api_views.py:434`) would need it added. If the user rules for
(b), this plan is re-issued; no task below survives as
written.

### Ruling 2 — default: no data migration; an audit query instead

Under (a), a row at rest whose template contains a backslash changes meaning on deploy. The default is
**no automatic rewrite**: the maintainer runs the audit query in the PR description and edits any row
it finds by hand. There is no way to know from the bytes whether `\1` was Python intent or a
literal-backslash intent that happened to work by accident, and a wrong automatic rewrite is worse
than a listed row.

Alternative, if the user prefers it: a data migration over `M3UAccountProfile.replace_pattern` and
`ChannelGroupM3UAccount.custom_properties["name_replace_pattern"]` applying one token walk —
`\\`→`\`, `\N` and `\g<N>` → `$N`, `\g<name>` → `$<name>`, every other backslash sequence left as-is
(those produced control bytes or raised, so no working template depended on them). It is a separate
task with its own tests and a no-op reverse; if ruled for, it is added as Task 6 in a plan amendment,
not improvised.

---

## Measured at seed

`regex.sub("(a)", convert_js_numbered_backreferences(t), "a")` at seed, the same through the proposed
helper (Appendix A), and Node 22's `"a".replace(/(?<n>a)/g, t)`. `→` means literal output equal to
the template. All five sites give the seed column today; `transform_url` was checked end to end for
the first three rows.

| template `t` | seed (Python parser sees the backslash) | proposed (a) | JavaScript |
|---|---|---|---|
| `[\0]` | `[\x00]` — NUL | `[\0]` | `[\0]` |
| `[\x01]` | `[\x01]` | `[\x01]` literal | literal |
| `[\n]` | newline | literal | literal |
| `[\1]` | `[a]` — group 1 | literal | literal |
| `[\g<1>]` | `[a]` | literal | literal |
| `[\\]` | `[\]` | `[\\]` | `[\\]` |
| `[\g<nope>]` | **raises `IndexError: unknown group`** (F3) | literal | literal |
| `[\z]`, `[\q]` | raises `regex.error: bad escape` | literal | literal |
| `[\u0041]` | `[A]` | literal | literal |
| `[\N{BULLET}]` | `[•]` | literal | literal |
| `[\8]`, `[\12]` | raises `invalid group reference` | literal | literal |
| `[\01]` | `[\x01]` | literal | literal |
| `[\t]`, `[\b]`, `[\a]` | tab, backspace, bell | literal | literal |
| `a\` (trailing) | raises `bad escape (end of pattern)` | `a\` | `a\` |
| `[\$1]` | `[\g<1>]` — the `$` rewrite's own backslash | `[\a]` | `[\a]` |
| `$1`, `$01`, `[$0]`, `$<n>` | `a`, `a`, `[$0]`, `a` | unchanged | same |
| `$$`, `$$1`, `$&` | `$$`, `$a`, `$&` (F2, pre-existing) | unchanged | `$`, `$1`, `a` |
| `$<x>` (no such name) | raises `IndexError`, caller falls back | unchanged | `""` |

The proposed column matches JavaScript on every backslash row. The last two rows are F2's known
divergences and the `$<name>`-missing divergence; both predate #440, neither is in scope, and § ADR
records them.

**Order is load-bearing.** Escaping must run *before* the `$<name>` and `$n` rewrites, because both
rewrites emit backslashes (`\g<…>`). Measured with the `$<name>` rewrite first and the escape second:
`$<n>` gives the literal `\g<n>` instead of `a`. That is Task 2's break-check.

---

## Files this plan touches

| file | task | label |
|---|---|---|
| `apps/m3u/utils.py` | 1 | `apps.m3u.tests` |
| `apps/proxy/next_source.py` (`:289-290`, Gate 2 module) | 2 | `apps.proxy.tests` |
| `apps/proxy/vod_proxy/views.py` (`:634-635`) | 2 | `apps.proxy.vod_proxy.tests` |
| `apps/m3u/tasks.py` (`:3119-3120`) | 2 | `apps.m3u.tests` |
| `apps/m3u/tests/test_replace_template_backslash.py` (new) | 1, 3 | `apps.m3u.tests` |
| `apps/proxy/tests/test_transform_url_backslash.py` (new) | 3 | `apps.proxy.tests` |
| `apps/proxy/vod_proxy/tests/test_transform_url_backslash.py` (new) | 3 | `apps.proxy.vod_proxy.tests` |
| `apps/m3u/tests/test_property_backreferences.py` (the one existing test module that changes) | 4 | `apps.m3u.tests` |
| `docs/adr/0007-m3u-replace-templates-use-javascripts-substitution-grammar.md` (new) | 5 | none |

Not touched, deliberately: `apps/m3u/tasks.py:2631` and `apps/channels/api_views.py:404` (the two
rename sites already call `convert_js_numbered_backreferences`, which Task 1 changes underneath them —
their `$n`-only grammar gains the backslash rule with no edit); `dispatcharr/consumers.py` (calls
`transform_url`); `frontend/**` (constraint 9); `apps/channels/api_views.py:1552-1561`
(constraint 10); `CLAUDE.md` and `metrics/curated/` (constraint 8; #171 carried no bullet either).

## Overlap with in-flight work

Checked at seed with `gh pr list --repo D10Scot/Dispatcharr --state open`: the four open PRs
(#493–#496) are docs and CI-comment changes and touch none of this plan's files. The
implementer re-runs `git merge-tree --write-tree` against any open PR touching the four production
files before pushing; the nearest known neighbours:

| file | who else | risk |
|---|---|---|
| `apps/m3u/tasks.py` | fixplan E's remaining PRs (lock messages around `:1555`, `:3502-3514`, `:3891`) | None at function level; this plan edits two lines inside `get_transformed_credentials` (`:3119-3120`). |
| `apps/proxy/next_source.py` | J-3's `test_tune_path_query_ledger.py` pins the module's *model* imports by qualname and its `.objects` count | None by construction: the import this plan touches is a function, and no ORM read is added. |
| `apps/proxy/vod_proxy/views.py` | fixplan B/D hunks at `:862`, `:1410`, `:1447`, `:1468-1478` | Context-only rebase at worst; `_transform_url` is at `:621-646`. |

---

## Design

One helper module, `apps/m3u/utils.py`, owns the whole JS-to-Python template rewrite. Appendix A has
the exact hunks.

- `_escape_template_backslashes(template)` — `template.replace("\\", "\\\\")`. Doubling every
  backslash makes the Python parser emit each one literally; it is total (never raises) and it is the
  only line that implements the ruling.
- `_convert_js_named_groups(template)` — the `\$<([^>]+)>` → `\g<\1>` rule, moved verbatim from the
  three URL sites. Its `[^>]+` name grammar is kept as-is (JS's is stricter; out of scope).
- `_convert_js_numbered_groups(template)` — #440's `\$(0[1-9]|[1-9]\d?)` → `\g<\1>` rule, unchanged.
- **`convert_js_numbered_backreferences(template)`** (existing public name, both rename sites keep
  calling it) becomes `numbered(escape(template))`. Its docstring gains the ruling.
- **`convert_js_replacement_template(template)`** (new public name) is
  `numbered(named(escape(template)))`. The three URL sites call it and delete their own inline
  `$<name>` line, so the rewrite exists in one place rather than three-plus-one.

Why two public names rather than one: the rename fields have never accepted `$<name>` (neither rename
site converts it), and adding it there would be a grammar *extension* to a field this issue does not
mention. The URL fields have always accepted it. Keeping the split keeps this PR to the ruling.

What this does **not** change: `$$`, `$&`, `` $` ``, `$'` stay literal (F2); a `$nn` naming a group the
pattern lacks still raises and each caller still falls back (the `$10` rows of
`apps/m3u/tests/test_rename_preview_parity.py:40-81` are refused by both the preview and the sync, as #440 left them — parity holds because both refuse); a
`$<name>` naming a missing group still raises `IndexError` inside the three URL sites' `except Exception`
and falls back to the original URL. All pre-existing, all recorded in the ADR.

---

## Tasks

### Task 0 — worktree, container, red at seed

1. `cd /Users/dion/git/Dispatcharr && git worktree add .worktrees/fix-452 -b fix/452-replace-template-backslash main`.
   Confirm `git -C .worktrees/fix-452 log -1 --format=%H` is the seed or a descendant of it
   (`git merge-base --is-ancestor 36e4ce10 HEAD`).
2. Start the private container (constraint 6).
   `docker exec -w /repo -e DJANGO_SECRET_KEY=hook-test-secret fix-452 python manage.py check`
   must exit 0 before anything else.
3. Reproduce at seed, so the PR description can quote it:
   ```
   docker exec -w /repo -e DJANGO_SECRET_KEY=hook-test-secret -e DJANGO_SETTINGS_MODULE=dispatcharr.settings_test -e TEST_USE_SQLITE=1 fix-452 \
     python -c "import django; django.setup(); import logging; logging.disable(logging.CRITICAL)
   from apps.proxy.next_source import transform_url
   print(repr(transform_url('a', '(a)', '[\\\\0]')))"
   ```
   Expected `'[\x00]'`. Keep the line.

### Task 1 — the helper (`apps/m3u/utils.py`) and its unit tests

1. Apply Appendix A hunk 1 to `apps/m3u/utils.py`.
2. Create `apps/m3u/tests/test_replace_template_backslash.py` with module docstring naming #452 and
   the ruling, and class `ReplaceTemplateBackslashTests(SimpleTestCase)`:
   - `test_backslash_escapes_are_literal_not_control_bytes` — one `subTest(template=…)` per template
     in this list, asserting `regex.sub("(a)", convert_js_replacement_template(t), "a") == t` **and**
     the same through `convert_js_numbered_backreferences`:
     `[\0]`, `[\x01]`, `[\n]`, `[\1]`, `[\g<1>]`, `[\\]`, `[\g<nope>]`, `[\z]`, `[\u0041]`, `[\8]`,
     `[\01]`, `[\t]`, `a\` (write these as Python string literals with doubled backslashes; a raw
     string cannot end in a backslash). The `[\0]` row also asserts `"\x00" not in result`.
   - `test_dollar_tokens_still_substitute_beside_a_backslash` — on pattern `(?<n>a)` and text `a`:
     `\$1` → `\a`; `[$1]\` → `[a]\`; `$<n>` → `a`; `$01` → `a`; `[$0]` → `[$0]`.
   - `test_named_group_rewrite_runs_after_backslash_escaping` — `$<n>` on `(?<n>a)` gives `a`. This is
     the ordering pin; its docstring states the wrong-order output `\g<n>`.
   - `test_a_literal_g_angle_is_text_not_a_group_reference` — `\g<nope>` through
     `convert_js_numbered_backreferences` on `(a)`/`a` returns the literal and raises nothing (F3).
   - `test_numbered_helper_does_not_convert_named_groups` — `$<n>` through
     `convert_js_numbered_backreferences` stays `$<n>` (the rename grammar is unchanged by design).
3. Run `apps.m3u.tests`. Green.
4. **Break-check (helper).** Make `_escape_template_backslashes` return its argument unchanged. The
   `[\0]` subTest must redden with `AssertionError: '[\x00]' != '[\\0]'`, and `[\g<nope>]` with
   `IndexError: unknown group`. Revert; green.

### Task 2 — the three URL sites

1. Apply Appendix A hunks 2–4: each site's two lines
   ```python
   safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', <template>)
   safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)
   ```
   become one, `safe_replace_pattern = convert_js_replacement_template(<template>)`, and each
   import of `convert_js_numbered_backreferences` at those three sites becomes an import of
   `convert_js_replacement_template` (`next_source.py:31` module-level; `vod_proxy/views.py:626`
   function-local; `tasks.py:34` module-level — check nothing else in `tasks.py` still needs the old
   name: the rename site at `:2631` does, so `tasks.py` imports **both**).
2. `docker exec -w /repo -e DJANGO_SECRET_KEY=hook-test-secret fix-452 python manage.py check` — exit 0 (the boot trap: `next_source.py`
   already imported `apps.m3u.utils` at seed, so no new module enters its closure).
3. **Break-check (ordering).** In `convert_js_replacement_template` swap the escape and named-group
   steps (`numbered(escape(named(t)))`). `test_named_group_rewrite_runs_after_backslash_escaping`
   must redden with `AssertionError: '\\g<n>' != 'a'`. Revert; green.

### Task 3 — end-to-end pins at the three URL sites

1. `apps/proxy/tests/test_transform_url_backslash.py`, class `TransformUrlBackslashTests(SimpleTestCase)`:
   - `test_transform_url_backslash_zero_is_literal_not_a_nul_byte` —
     `transform_url("http://h/a/1.ts", "(a)", "[\\0]") == "http://h/[\\0]/1.ts"` and no `\x00`.
   - `test_transform_url_backslash_one_is_not_a_backreference` — template `\1` gives a literal `\1`
     in the URL, not `a`.
   - `test_transform_url_named_token_still_substitutes` — `$<n>` on `(?<n>a)` gives `http://h/a/1.ts`
     (unchanged behaviour, pinned because the site's own `$<name>` line is deleted in this PR).
2. `apps/proxy/vod_proxy/tests/test_transform_url_backslash.py`, class
   `VodTransformUrlBackslashTests(SimpleTestCase)`, using the `SimpleNamespace` profile shape of the
   sibling `test_transform_url_backreferences.py`:
   - `test_vod_transform_backslash_zero_is_literal_not_a_nul_byte` — same expectation as above.
   - `test_vod_transform_named_token_still_substitutes`.
3. In `apps/m3u/tests/test_replace_template_backslash.py`, class
   `GetTransformedCredentialsBackslashTests(TestCase)`, modelled on
   `test_js_backreference_conversion.py:61-83` (account via `M3UAccount.objects.create`, default
   profile from the `post_save` signal): the XC simple-mode shape, `search_pattern="myuser/mypass"`,
   `replace_pattern="myuser/p\\0ss"`; assert `transformed_password == "p\\0ss"`, no `\x00` in either
   credential, and `transformed_username == "myuser"`. Docstring: grounds 2 of the ruling — this is the
   template the SPA writes for the operator.
4. Same module, class `RenamePreviewBackslashTests(TestCase)`, modelled on
   `test_rename_preview_parity.py:86-160` (admin `APIClient`, one `M3UAccount`, one `ChannelGroup`,
   one `Stream` named `Alpha 1` in it), calling
   `GET /api/channels/streams/regex-preview/?channel_group=<g>&find=(\d+)&replace=[\0]`
   (plus `m3u_account_id=<account id>`, the parameter name at `apps/channels/api_views.py:347`):
   - `test_rename_preview_backslash_zero_is_literal` — 200, `find_matches[0]["after"] == "Alpha [\\0]"`.
   - `test_rename_preview_literal_g_angle_does_not_500` — `replace=\g<nope>` gives 200 with
     `after == "Alpha \\g<nope>"` and no `find_error` key in the body (it is omitted, not null, when nothing failed — `api_views.py:475`). F3's rename-preview crash cannot be reached.
5. Run `apps.m3u.tests`, `apps.proxy.tests`, `apps.proxy.vod_proxy.tests`. Green.
6. **Break-check (site).** Revert only `apps/proxy/vod_proxy/views.py` to its seed two-line form
   (`git show "36e4ce10:apps/proxy/vod_proxy/views.py" | sed -n 626,635p` is the text). The VOD test
   must redden with `AssertionError: 'http://h/[\x00]/1.ts' != 'http://h/[\\0]/1.ts'` and be the
   only failure in `apps.proxy.vod_proxy.tests`. Revert; green.

### Task 4 — widen the category-I property alphabet (the one existing test module that changes)

`apps/m3u/tests/test_property_backreferences.py` was written to be widened here; its docstring says
so twice. Change only these, and list each in the PR description:

| where | before | after |
|---|---|---|
| module docstring, property 1 paragraph | "Generated templates exclude the backslash: the helper hands a backslash straight to Python's replacement-template parser, which JavaScript never does, so a template containing one reopens exactly this symptom (#452). The alphabet widens to include the backslash once #452 is ruled." | "Generated templates include the backslash: since #452 every backslash is literal (ADR 0007), so this property is what proves the ruling holds for every escape Python's template parser knows." |
| comment above `templates` (`:73-77`) | the four-line "no backslash … widens once #452 is ruled" comment | one line: `# Templates as the operator types them, backslash included (#452: literal).` |
| `templates` alphabet (`:78`) | `"ab/-[]$0123456789x"` | `"ab/-[]$0123456789x\\"` |
| `js_templates` literal `first` (`:104`) | `st.sampled_from("ab/-[]x")` | `st.sampled_from("ab/-[]x\\")` |
| `js_templates` literal `rest` alphabet (`:105`) | `"ab/-[]x0123456789"` | `"ab/-[]x0123456789\\"` |
| `test_conversion_never_introduces_a_character_absent_from_target_and_template` decorators (`:152-155`) | two `@example(... data=None)` rows | a third: `@example(case=(r"(a)", 1), data=None)` with the comment `# #452: "[\\0]" reached Python's template parser as a NUL byte.` |
| the `data is None` dict inside that test (`:160-166`) | two entries | a third: `(r"(a)", 1): ("[\\0]", "a")` |
| `_MATCHING_SEED` / `targets` | unchanged | unchanged |

No assertion, `max_examples` or `except` clause changes; the one `@example` added is a new row, not a changed one. `_apply`'s
`except (regex.error, IndexError)` stays: a `$nn` naming a missing group still raises by design.

1. Apply. Run `apps.m3u.tests` twice (`derandomize=True` makes the draw deterministic; the second run
   is the hook's own).
2. **Red at seed, not a break-check** (the property is not new, so constraint 5's wrong-edit does not
   apply; instead prove the widening bites): copy the widened module onto a seed checkout
   (`git stash` is forbidden — use `git worktree add /tmp/… 36e4ce10` or a second private container)
   and run it. `test_conversion_never_introduces_a_character_absent_from_target_and_template` must
   fail: the new `@example` row is deterministic and gives
   `AssertionError: {'[', '\x00', ']'} not less than or equal to {'a', '[', '\\', '0', ']'}` (or the
   same sets in another order); the widened draws will usually add a second falsifying example of
   their own. If the `@example` row passes at seed, STOP: the fix leaked into the seed checkout.

### Task 5 — the ADR

Create `docs/adr/0007-m3u-replace-templates-use-javascripts-substitution-grammar.md` in the house
shape (`# 7. <title>`, `Date: 2026-09-25`, `## Status` Accepted, `## Context`, `## Decision`,
`## Consequences`), from § The ruling above: Context is #171/#440 plus the three previews; Decision
is (a) in one sentence plus the token list **per field**: the three URL fields (M3U-profile
`replace_pattern` on the live, VOD and XC-credential transforms) take `$n`, `$nn` and `$<name>`; the
two rename fields (`name_replace_pattern` on the auto-sync rename and its preview) take `$n` and
`$nn` only, and `$<name>` is literal there as it always was. Consequences list (i) the migration note
and the audit query, (ii) the sixth site as a filed follow-up, (iii) the recorded divergences that
remain (`$$`, `$&`, `` $` ``, `$'`, the two-digit fallback, `$<missing>`), (iv) that
`apps/m3u/utils.py` is the only place the grammar is implemented, that
`test_property_backreferences.py` enforces the rename variant (it exercises only
`convert_js_numbered_backreferences`, `:84`) and that `test_replace_template_backslash.py` pins the
URL variant and the escape-first ordering. Under 120 lines. No
test; `python scripts/ci_backend_test_labels.py docs/adr/0007-….md` is `[]`, so the commit gate runs
nothing for it — commit it with the code, not alone.

### Task 6 — gate, fresh DB, push

1. `scripts/coverage_live_path_isolated.sh --gate` from the worktree. Expect `missing` unchanged (33
   at the 2d-5 floor, or whatever `scripts/coverage_live_path.floor` says at your base) and
   `statements` one lower than at your base (one statement deleted in `next_source.py`). Paste the
   result line.
2. Each of the three labels once **without** `--keepdb`, plus the `tests` label (routes
   `tests/test_websocket_consumer_filter.py`, whose `m3u_profile_test` cases mock `transform_url`
   (`:232-236`) or drive it with `$n` templates only — the run is #440-style parity, not coverage of
   this PR's change, so do not report it as such; CI does not route it for these paths, so run it
   yourself as #440 did).
3. `python scripts/check_credential_logging.py` over the touched `.py` files (the edit hook runs it;
   confirm exit 0 in the log).
4. Stage; commit with the message in § PR section; push; open the PR as a **draft** against `main`
   with the description below; report the head SHA.

---

## PR section: `fix/452-replace-template-backslash`

- **Closes** #452. **Ruling** (a), recorded as ADR 0007.
- **Files** the nine in § Files this plan touches.
- **Labels** `apps.m3u.tests`, `apps.proxy.tests`, `apps.proxy.vod_proxy.tests` — three, for the same
  reason #440 gave: the single-helper design exists so the five sites cannot disagree between merges.
- **Existing tests changed:** `apps/m3u/tests/test_property_backreferences.py`, exactly the Task 4
  table. **Existing tests that must stay green unmodified:** `test_js_backreference_conversion.py`
  (all), `test_rename_preview_parity.py` (its `$10` rows are refused by both paths, as before),
  `TransformUrlBackreferenceTests` in `test_next_source_edges.py`,
  `vod_proxy/tests/test_transform_url_backreferences.py`, `tests/test_websocket_consumer_filter.py`.
- **Upstreamable** partly: the `apps/m3u/utils.py` hunk and the `tasks.py` hunk would apply; upstream's
  URL transform lives elsewhere (`apps/proxy/ts_proxy/url_utils.py`) with the pre-#440 rewrite, so it
  would need both rulings at once.
- **Commit message** (first line under 72 characters):

  ```
  fix(m3u,proxy): backslash in a replace template is literal (#452)
  ```

- **PR description draft.**

  > **fix(m3u,proxy): a backslash in a replace template is literal text, per ADR 0007 (#452)**
  >
  > #440 gave `$n` JavaScript's grammar; the backslash still reached Python's replacement-template
  > parser, so `\0` put a NUL byte into a stream URL, `\x01` a control byte and `\n` a newline, while
  > the SPA's own preview (`String.prototype.replace`) showed the operator literal text. This PR
  > adopts the ruling in ADR 0007: **a replace template is JavaScript's replacement grammar in full —
  > `$1`–`$99` and `$01`–`$09` substitute, plus `$<name>` on the three URL fields (never on the two
  > rename fields, where it was always literal); every other character, backslash included, is
  > literal.** One helper module implements it (`apps/m3u/utils.py`: escape, then `$<name>`, then
  > `$n`; the order is load-bearing and pinned), the three URL sites call the new
  > `convert_js_replacement_template` and lose their own `$<name>` line, and the two rename sites gain
  > the rule through the helper they already call.
  >
  > **Migration note.** A template written with Python-style `\1` (never documented, but accepted
  > until now) must become `$1`. Audit an instance before deploying:
  >
  > ```python
  > from apps.m3u.models import M3UAccountProfile
  > from apps.channels.models import ChannelGroupM3UAccount
  > M3UAccountProfile.objects.filter(replace_pattern__contains="\\").values_list("id", "name", "replace_pattern")
  > [(r.id, r.custom_properties["name_replace_pattern"]) for r in ChannelGroupM3UAccount.objects.filter(custom_properties__has_key="name_replace_pattern") if "\\" in (r.custom_properties.get("name_replace_pattern") or "")]
  > ```
  >
  > Also closed as a side effect: the #440 review's F3 — a literal `\g<name>` can no longer raise
  > `IndexError` on the rename paths, because no backslash reaches the parser. Not changed, and now
  > recorded in the ADR: `$$`, `$&`, `` $` `` and `$'` stay literal; a `$nn` or `$<name>` naming a
  > missing group still raises and the caller falls back. Not touched: the bulk channel rename's own
  > rewrite (`apps/channels/api_views.py:1552-1561`, same hole, filed as #<n>), the SPA (already
  > correct), `CLAUDE.md`, `metrics/curated/`.
  >
  > **Red at seed** (`36e4ce10`): `transform_url('a', '(a)', '[\\0]')` → `'[\x00]'`; every new test
  > names the mechanism (`'[\x00]' != '[\\0]'`, `IndexError: unknown group`); the widened property
  > test fails at seed with <paste Hypothesis' falsifying example>.
  >
  > **Break-checks.** <three rows: helper escape removed → `'[\x00]' != '[\\0]'`; order swapped →
  > `'\\g<n>' != 'a'`; VOD site reverted → the VOD test alone red>.
  >
  > **Gate 2.** `coverage_live_path_isolated.sh --gate`: <paste: floor missing, this run missing,
  > statements −1>.
  >
  > **Tests run** (fresh DB, no `--keepdb`, own container): <table: the three labels + `tests`>.
  >
  > **Existing test changed:** `apps/m3u/tests/test_property_backreferences.py` — the template
  > alphabets gain the backslash and two comments say why (before/after table in the plan, Task 4).
  > No other existing test changed.
  >
  > Closes #452.
  >
  > 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Follow-ups (file, do not fix here)

1. **The sixth site.** `translate_js_replacement` (`apps/channels/api_views.py:1552-1561`, the bulk
   channel rename) applies `$$`, `$&`, `$<name>` and `\$(\d+)` rewrites and no backslash escape, on the
   same Python parser: `[\0]` in a bulk-rename replacement puts a NUL into a channel name by the same
   mechanism, and its `$0` still means the whole match where its own JS preview
   (`frontend/src/utils/forms/ChannelBatchUtils.js:125-148`) shows `$0` literally. #440 excluded it by
   name; ADR 0007 rules it should follow the same grammar. One issue, small.
2. **UI copy.** The two replace-field descriptions could say "backslashes are literal". Frontend-only.
3. **The F2 divergences** (`$$`, `$&`, `` $` ``, `$'`, the two-digit fallback) and `$<missing>` raising
   where JS gives `""`: pre-existing, now recorded in the ADR; an issue if anyone wants them.
4. **`$<name>` name grammar** is `[^>]+` here and an identifier in JS. Cosmetic.
5. **XC simple mode's `search_pattern` is unescaped too.** `applyXcSimplePatterns`
   (`M3uProfileUtils.js:146`) writes the *base* username and password verbatim into the regex
   `search_pattern`, so a base password containing a regex metacharacter never matches and the
   profile silently does nothing. Grounds 2 of the ruling fixes the *replace* side only; this is a
   separate defect on the search side and ADR 0007 must not imply simple mode is round-trip safe.

---

## Appendix A: hunks against `36e4ce10`

Written as the diff the implementer applies. Line numbers are the seed's.

### Hunk 1 — `apps/m3u/utils.py` (replace `:81-102`)

```python
def _escape_template_backslashes(template):
    """Make every backslash in *template* literal to Python's template parser.

    JavaScript's ``String.prototype.replace`` gives a backslash no meaning in
    a replacement string; Python's ``re``/``regex`` replacement-template
    parser reads ``\\0`` as a NUL byte, ``\\x01`` as a control byte, ``\\n``
    as a newline and ``\\1`` as a backreference. Doubling every backslash
    first makes the parser emit each one as itself (#452, ADR 0007). This
    must run BEFORE either ``$`` rewrite below: both emit ``\\g<...>``, and
    escaping after them would turn those into literal text.
    """
    return template.replace("\\", "\\\\")


def _convert_js_named_groups(template):
    # $<name> -> \g<name>. The name grammar is deliberately loose ([^>]+);
    # the regex module resolves it, and a missing name raises IndexError,
    # which every URL-site caller catches and falls back on.
    return regex.sub(r"\$<([^>]+)>", r"\\g<\1>", template)


def _convert_js_numbered_groups(template):
    # JavaScript's own $n/$nn grammar (#171): exactly two digits 01-99, or
    # one digit 1-9, and nothing longer. See convert_js_numbered_backreferences.
    return regex.sub(r"\$(0[1-9]|[1-9]\d?)", r"\\g<\1>", template)


def convert_js_numbered_backreferences(replacement):
    """Translate a JS-style rename template to a Python ``regex`` template.

    <keep the existing docstring's second and third paragraphs verbatim, then append:>

    Since #452 (ADR 0007) the template is JavaScript's replacement grammar
    in full: a backslash is literal text, never an escape, so ``\\0`` cannot
    become a NUL byte and ``\\1`` is not a backreference. This is the
    rename-field variant: ``$n``/``$nn`` only, no ``$<name>``. The URL
    fields use ``convert_js_replacement_template``.
    """
    return _convert_js_numbered_groups(_escape_template_backslashes(replacement))


def convert_js_replacement_template(replacement):
    """Translate a JS-style URL replace template to a Python ``regex`` template.

    The three URL transforms (every live tune via ``apps.proxy.next_source.
    transform_url``, the VOD transform, and the XC credential transform)
    accept ``$<name>`` as well as ``$n``/``$nn``; everything else, the
    backslash included, is literal (#452, ADR 0007). Order matters:
    backslashes are escaped first, because both rewrites emit them.
    """
    return _convert_js_numbered_groups(
        _convert_js_named_groups(_escape_template_backslashes(replacement))
    )
```

### Hunk 2 — `apps/proxy/next_source.py`

`:31` — `from apps.m3u.utils import convert_js_numbered_backreferences` →
`from apps.m3u.utils import convert_js_replacement_template`.

`:287-290` — the comment and two assignments become:

```python
        # JS replace grammar -> Python template: backslash literal, $<name>, $n
        # (apps.m3u.utils, ADR 0007). Fixed conversion patterns only; the
        # timeout is reserved for the user's search pattern.
        safe_replace_pattern = convert_js_replacement_template(replace_pattern)
```

### Hunk 3 — `apps/proxy/vod_proxy/views.py`

`:626` — `from apps.m3u.utils import convert_js_numbered_backreferences` →
`from apps.m3u.utils import convert_js_replacement_template`.

`:633-635` — the comment and two assignments become:

```python
        # JS replace grammar -> Python template (ADR 0007): backslash literal,
        # $<name>, $n.
        safe_replace_pattern = convert_js_replacement_template(replace_pattern)
```

### Hunk 4 — `apps/m3u/tasks.py`

`:32-37` (the `from .utils import (...)` block) — add `convert_js_replacement_template` beside
`convert_js_numbered_backreferences`; the rename site at `:2631` keeps the latter.

`:3117-3120` — the comment and two assignments become:

```python
                # JS replace grammar -> Python template (ADR 0007): backslash
                # literal, $<name>, $n. The regex module accepts JS-style
                # (?<name>...) named groups natively.
                safe_replace_pattern = convert_js_replacement_template(profile.replace_pattern)
```

Statement count: `utils.py` +4 functions; each URL site −1 statement; `next_source.py` is the only
Gate 2 module, so the gate's `statements` moves by exactly −1.

## Appendix B: the ruling's measurement script

The probe that produced § Measured at seed, for re-running on a later tree; run inside a test
container with `DJANGO_SETTINGS_MODULE=dispatcharr.settings_test TEST_USE_SQLITE=1`:

```python
import regex, logging
logging.disable(logging.CRITICAL)
from apps.m3u.utils import convert_js_numbered_backreferences as conv
B = "\\"
cases = ["[\\0]", "[\\x01]", "[\\n]", "[\\1]", "[\\g<1>]", "[\\\\]", "[\\g<nope>]", "[\\z]",
         "[\\u0041]", "[\\N{BULLET}]", "[\\8]", "[\\01]", "[\\t]", "a\\", "[\\$1]"]
for t in cases:
    try:
        print(repr(t), "->", repr(regex.sub("(a)", conv(t), "a")))
    except Exception as e:
        print(repr(t), "-> RAISES", type(e).__name__, e)
def js(t):  # the proposed helper, inline
    t = t.replace(B, B + B)
    t = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', t)
    return regex.sub(r"\$(0[1-9]|[1-9]\d?)", r"\\g<\1>", t)
for t in cases + ["$1", "$01", "[$0]", "$<n>", "$$", "$$1", "$&", "$<x>"]:
    try:
        print(repr(t), "->", repr(regex.sub(r"(?<n>a)", js(t), "a")))
    except Exception as e:
        print(repr(t), "-> RAISES", type(e).__name__, e)
```

And the JavaScript column: `node -e 'for (const t of [...]) console.log(JSON.stringify("a".replace(/(?<n>a)/g, t)))'`.
