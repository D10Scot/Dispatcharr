# Fix plan #452 — a backslash in an M3U replace template is literal text, as in JavaScript

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal.** Remove the defect #452 reports: a backslash in an M3U `replace_pattern` (and in an auto-sync rename's
`name_replace_pattern`) still reaches Python's replacement-template parser, so `\0` puts a NUL byte
into a live stream URL, a VOD URL, an XC credential or a channel name. #440 (#171) closed the same
symptom for `$0`/`$01`. This plan asks for a grammar ruling, recommends one, and plans it in full.

**Issue.** #452 (planned here). No user ruling exists; § Ruling recommends a default and § If the user
rules for the alternative bounds the other one.

**Seed SHA: `36e4ce10`** (`main`, 2026-09-25). Every `file:line` below was opened there. Every hunk in
the appendices was applied to an export of that SHA and run there, in a private test container
(`plan-452`, bind-mounted at the export, never the shared `dispatcharr-testrunner`), red before the
production hunks and green after, and every break-check below was run red there. Nothing but this
document is committed.

**Architecture.** One shared helper module (`apps/m3u/utils.py`) owns the JavaScript-to-Python
replacement-template rewrite; five call sites consume it. The fix is inside the helper plus a one-line
call change at the three URL sites. No model, serializer, migration, frontend, Go or nginx change.

**Tech stack.** Python 3.13.15 (container) and the `regex` module `2026.7.19` (`uv.lock:1878-1879`);
Hypothesis `6.165.10`. The JavaScript oracle is Node **v22.14.0** `String.prototype.replace` with a
global `RegExp`, the engine the SPA preview runs. Pure-Python measurements used a scratch venv
(CPython 3.13.2, same `regex` pin) and match the container.

**Inputs.** The #452 issue body; PR #440 (merge `cbae804d`); the #171 analysis and PR C-4 section of
`docs/superpowers/plans/2026-09-23-fixplan-C-input-crashes.md`; the merged property module
`apps/m3u/tests/test_property_backreferences.py`, which waits on this ruling.

**Planner's worktree.** `.worktrees/plan-452`, branch `docs/plan-452-replace-template-backslash`.
Only this file is committed.

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
   green. New behaviour gets a new test named after the defect. **This PR changes exactly one existing
   test module**, `apps/m3u/tests/test_property_backreferences.py`, whose own docstring says its
   template alphabet widens "once #452 is ruled"; § Existing tests deliberately changed lists every
   line. Two other existing files gain new tests appended after their existing ones
   (`apps/proxy/tests/test_next_source_edges.py`, one new class;
   `apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py`, two new methods); no existing
   test in either changes.
5. **The appendices are the deliverable, verbatim.** Extract them with § Appendix extraction and
   `git apply` them. Do not retype them. Each has a SHA-256 the extraction must reproduce. If a hunk
   does not apply to your base, STOP and report; do not hand-merge.
6. **Test container.** The `PostToolUse` hooks always use the shared container `dispatcharr-testrunner`,
   whose mount decides which tree is tested (`CLAUDE.md` § Test hooks). `git apply` does not fire the
   hook (it fires on `Write|Edit` only), which is one more reason to apply the appendices rather than
   retype them. For runs you launch yourself use a private container:
   `DISPATCHARR_TEST_CONTAINER=fix-452 DISPATCHARR_TEST_DB_VOLUME=fix-452-db CLAUDE_HOOK_REPO_ROOT=<wt> /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh`,
   and run labels with the hook's own environment:

   ```bash
   docker exec -w /repo \
     -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
     -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
     -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
     -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
     fix-452 /dispatcharrpy/bin/python manage.py test <label-or-module> --noinput -v1
   ```

   Flush Redis before each label (`docker exec fix-452 redis-cli flushall`), as the hook and CI do.
   Never pass `--keepdb`: every figure in this plan is from a fresh test database. Remove `fix-452` and
   `fix-452-db` by name when done.
7. **Gate 2.** `apps/proxy/next_source.py` is in `scripts/coverage_live_path.coveragerc:44`. Run the
   isolated gate before push (Task 5). `missing` must not move; if it does, STOP. A green label run
   does not imply a green gate.
8. **Closing keywords.** The implementation PR body and its squash commit carry GitHub's closing
   keyword for #452. This plan writes that line as the slot `<closing keyword> #452.`, whose value is
   the word `Closes`, so that neither this document nor its own PR ever carries a live closing keyword
   (a docs merge that closes an issue has happened here before).
9. **No `metrics/curated/` edit.** `grep -rn 452 metrics/curated/` is empty at seed (exit 1): #452 has
   no `defects.yml` row, is not a CLAUDE.md "Known defects" bullet, an e2e `test.fail()` pin or a
   parity-matrix row. The dashboard's `property_tests` tile counts modules, and this PR adds none.
10. **Branch** `fix/452-replace-template-backslash`. Nothing under `docker/`, `relay/` or
    `docker/nginx.conf` changes, so it does not take the `migration/` prefix.
11. **Nothing outside the eight files in Appendices A and B changes.** In particular: no frontend file,
    no serializer, no migration, no `CHANGELOG.md` (§ Migration note says where the note goes and why),
    and `apps/channels/api_views.py` is not edited (its rename preview changes behaviour through the
    helper, and is tested through its endpoint).

---

## #452: a backslash in the replace template reaches Python's template parser

### Root cause

`convert_js_numbered_backreferences` (`apps/m3u/utils.py:81-102`) rewrites JavaScript's `$n` tokens to
Python's `\g<n>` and hands everything else through untouched (`:102`,
`return regex.sub(r"\$(0[1-9]|[1-9]\d?)", r"\\g<\1>", replacement)`). A backslash in the operator's
template is therefore passed to `regex.sub`'s own template parser, which reads it as an escape. In
JavaScript a backslash in a replacement template has no meaning at all and is copied through literally
(ECMA-262 GetSubstitution recognises only `$`).

The five paths through the helper, at seed:

| # | path | call site | `$<name>` rewritten? | what catches a template error |
|---|---|---|---|---|
| 1 | live tune `transform_url`, and the WebSocket `m3u_profile_test` preview (`dispatcharr/consumers.py:163`) | `apps/proxy/next_source.py:289-290` (import `:31`) | yes, `:289`, **before** the helper | `except Exception` `:308` → original URL |
| 2 | VOD `_transform_url` | `apps/proxy/vod_proxy/views.py:634-635` (import `:626`) | yes, `:634`, before the helper | `except Exception` `:644` → original URL |
| 3 | XC `get_transformed_credentials` | `apps/m3u/tasks.py:3119-3120` (import `:34`) | yes, `:3119`, before the helper | `except Exception` `:3185` → base credentials |
| 4 | auto-sync rename | `apps/m3u/tasks.py:2631` | **no** | `except (regex.error, TimeoutError)` `:2638`; anything else reaches the per-stream `except Exception` `:2790` (stream counted failed) or, for a NUL that survives to `bulk_create`, the whole sync's `except Exception` `:3058` |
| 5 | auto-sync rename preview (`/api/channels/streams/regex-preview/`) | `apps/channels/api_views.py:404` (import `:33`) | **no** | `except (TimeoutError, re.error)` `:434` (`re` is `regex`, `:331`); anything else is a 500 |

`translate_js_replacement` (`apps/channels/api_views.py:1552-1561`, the channel **bulk**-rename action)
is a sixth, separate rewrite that does not call the helper. It is out of scope; § Follow-ups item 5
says why.

### Reproduced at seed

Python: the two rewrite shapes above, copied from `36e4ce10` (`url` = paths 1-3, `rename` = paths 4-5),
applied with `regex.sub(pattern, template, target)`. JavaScript: Node v22.14.0,
`target.replace(new RegExp(pattern, "g"), template)`. Pattern `(a)`, target `a`, unless noted.

| template | Python `url` | Python `rename` | JavaScript |
|---|---|---|---|
| `[\0]` | `'[\x00]'` (NUL) | `'[\x00]'` | `[\0]` |
| `[\x01]` | `'[\x01]'` | `'[\x01]'` | `[\x01]` |
| `[\n]` | `'[\n]'` (newline) | `'[\n]'` | `[\n]` |
| `[\t]` | `'[\t]'` (tab) | `'[\t]'` | `[\t]` |
| `[\1]` | `[a]` (group 1) | `[a]` | `[\1]` |
| `[\g<1>]` | `[a]` | `[a]` | `[\g<1>]` |
| `[\g<x>]` | `IndexError: unknown group` | `IndexError: unknown group` | `[\g<x>]` |
| `[\u0041]` | `[A]` | `[A]` | `[\u0041]` |
| `[\N{DIGIT ONE}]` | `[1]` | `[1]` | `[\N{DIGIT ONE}]` |
| `[\q]` | `error: bad escape \q at position 3` | same | `[\q]` |
| `[\\]` (two backslashes) | `[\]` (one) | `[\]` | `[\\]` (two) |
| `[\$1]` | `[\g<1>]` (literal text) | `[\g<1>]` | `[\a]` |
| `C:\path\$1` | `error: bad escape \p at position 4` | same | `C:\path\a` |
| `[\$<x>]`, pattern `(?<x>a)` | `[\g<x>]` (literal) | `[\$<x>]` | `[\a]` |
| `[$<x>]`, pattern `(?<x>a)` | `[a]` | `[$<x>]` (not rewritten) | `[a]` |

Every template without a backslash already matches Node for the `$n` grammar #440 adopted; the `$$`,
`$&`, `` $` ``, `$'`, `$10` and `$<name>` rows the issue lists are § Sub-questions.

Two consequences the issue body does not state, both measured at seed through the real code:

- **A `\0` in one group's rename template aborts the whole account's auto-sync.** The NUL survives the
  rename, reaches `bulk_create`, and PostgreSQL refuses it; `sync_auto_channels` returns
  `{'status': 'error', 'error': 'PostgreSQL text fields cannot contain NUL (0x00) bytes', 'channels_created': 0, ...}`
  (the new `test_rename_sync_keeps_a_backslash_literal`, red at seed). One group's template stops
  channel creation for every group on the account.
- **`\g<x>` in a rename template is an uncaught `IndexError` in the rename preview**, which reaches the
  client as a 500 (`apps/channels/api_views.py:434` catches only `TimeoutError`/`regex.error`), and in
  the sync counts every stream in the group as failed (`apps/m3u/tasks.py:2790`). The issue attributes
  this `IndexError` to `$<name>`; on the rename paths `$<name>` is never rewritten (last table row), so
  the reachable spelling is Python's own `\g<name>`.

### What the operator sees

This decides the ruling. The M3U-profile form renders exactly one "Result After Replace", and it is
computed **in JavaScript**: `getLocalReplaceResult` (`frontend/src/components/forms/M3UProfile.jsx:251-252`)
calls `applyRegex` (`frontend/src/utils/forms/M3uProfileUtils.js:34-42`), which is
`input.replace(new RegExp(pattern, 'g'), replacer)`. The server-side WebSocket preview is computed
(`dispatcharr/consumers.py:163`, through `transform_url`) and stored
(`frontend/src/WebSocket.jsx:576-580` → `setProfilePreview`, `frontend/src/store/playlists.jsx:144-147`),
but **nothing reads `profileResult` or `profileSearchPreview`**:
`grep -rn "profileResult\|profileSearchPreview" frontend/src` finds the store's own declaration and
setter (`playlists.jsx:11-12,144-147`) and the store's unit test
(`frontend/src/store/__tests__/playlists.test.jsx:17-18,32-33,304-305`); no component reads it. So for an M3U profile the only preview on screen already shows
`\1`, `\0` and `\x01` as literal text (table above, JavaScript column), and the help text on both
replace fields says "Use $1, $2, etc. to reference regex capture groups"
(`M3UProfile.jsx:309`, `:369`). An operator relying on Python-style `\1` in a URL profile has been
relying on behaviour the form's own preview contradicts on every keystroke.

The auto-sync rename is different: its preview is server-side (`LiveGroupFilter.jsx` → `api.js:326` →
`apps/channels/api_views.py:404`), runs the same helper as the sync, and so has always shown Python's
reading. Its only guidance is the placeholder `e.g. $1` (`AutoSyncAdvanced.jsx:320`). An operator
could have typed `\1` there and seen it work. That is the population option (a) breaks, and the
migration note is written for them.

User-facing documentation of `replace_pattern` outside the form: none. `grep -rln -i "replace_pattern\|replace pattern" --include='*.md' .`
(excluding `docs/superpowers/plans/` and `docs/superpowers/specs/`) finds only `CHANGELOG.md` entries
describing the feature (none states a grammar) and `e2e/COVERAGE.md:205`'s coverage gap row. The two
specs it also hits (`2026-08-29-e2e-xc-provider-emulation-design.md:90`,
`2026-09-01-e2e-coverage-completions-design.md:79,269,437`) are e2e design notes and state no grammar
either.

### Ruling — recommended default: (a), a backslash is literal text on all five paths

**Rule.** Inside the shared helper, double every backslash **first**, then rewrite `$<name>` (URL paths
only, as today) and then `$n` (as today). The backslash reaches the engine as `\\`, a literal
backslash; the `\g<...>` the two rewrites emit is produced after the doubling and so is never itself
escaped.

**Evidence for (a).**

1. It is what the operator sees for URL profiles (§ What the operator sees) and what the help text
   documents. After (a), the M3U-profile preview, the live transform, VOD and credentials agree on every
   row of the table above. Measured: the new URL-path rewrite reproduces Node's column on all fifteen
   rows, and the new rename-path rewrite on the thirteen backslash rows (the last two rows differ on the
   rename paths only because those never rewrite `$<name>`, which is pre-existing, § Follow-ups item 4).
2. It is the grammar #440 already adopted for `$n`. #452 is the remainder of the same decision, not a
   new one.
3. It removes a class, not a list. Under (a) a backslash can only ever reach the output as itself:
   the widened property ("no character in neither the target nor the template") holds over 200
   derandomized examples per property on an alphabet that now includes the backslash, where a denylist leaks whatever it forgot (break-check BC-1 found `\a`, a BEL byte, which
   neither the issue nor this plan's first table named).
4. Every template without a backslash is rewritten byte-for-byte as before, by construction (the
   doubling is the identity on such a template, and the two rewrites run in their seed order).
   Measured over 300,000 random backslash-free templates (seeded, length 0-14, over `$`, `<`, `>`, `a`,
   `b`, `0`, `1`, `2`, `9`, `x`, `/`, `-`, `g`, `&`, `'` and the backtick): identical to the seed
   rewrite on both the URL and the rename shape.

**What (a) breaks, for whom.** An operator whose stored template contains a backslash they meant
Python's way — `\1`, `\g<1>`, `\\` for one backslash — gets the backslash literally after upgrade:

- URL profile: the stream URL (or the XC credential) carries a literal `\1`, so the tune reaches the
  provider with a URL it will not recognise. The form's preview already showed this result.
- Auto-sync rename: on the next sync the channel names in that group become the literal template
  text (e.g. `\1`). The rename preview shows the new result before the next sync.

Both are found with two queries (measured in the container against a migrated database):

```python
from apps.m3u.models import M3UAccountProfile
from apps.channels.models import ChannelGroupM3UAccount
M3UAccountProfile.objects.filter(replace_pattern__contains="\\").values_list("m3u_account__name", "name", "replace_pattern")
ChannelGroupM3UAccount.objects.filter(custom_properties__name_replace_pattern__icontains="\\").values_list("m3u_account__name", "channel_group__name", "custom_properties__name_replace_pattern")
```

(`__icontains`, not `__contains`, on the JSON key: `__contains` there is JSON containment and returned
nothing for a row that has a backslash.) The fix for an operator is to write `$1` for `\1` and `$<name>`
for `\g<name>` (URL profiles only). A data migration that rewrites stored templates is rejected
(§ Follow-ups item 6).

### Option (b), and why "validation time" has no seam

(b) keeps `\1`-`\99` as groups and rejects `\0`, `\x`, `\u`, `\N` "at validation time". Neither half
survives contact with the tree:

- **There is no validation of either template's content anywhere.**
  `M3UAccountProfileSerializer.validate` (`apps/m3u/serializers.py:74-92`) checks only that the two
  patterns are non-empty, and returns early for the default profile before even that (`:77-80`); the
  default profile's patterns are editable (`:97`). Group templates are saved by
  `update_group_settings` (`apps/m3u/api_views.py:480-511`), a hand-rolled loop that checks the
  channel-number range and writes `custom_properties` through `ensure_custom_properties_dict` with no
  look at `name_replace_pattern`. Rows stored before the change bypass both. So (b) needs a runtime
  rejection inside the helper in any case — raising `regex.error` so the rename paths' narrow `except`
  (`tasks.py:2638`, `api_views.py:434`) falls back — plus two new write-time checks, plus tests for all
  three.
- **"Reject `\0`/`\x`/`\u`/`\N`" is a denylist, and it is already incomplete.** `\a` (BEL), `\b`,
  `\f`, `\v`, `\n`, `\t` all inject control bytes today; BC-1 below is exactly that shape and the
  widened property catches it with `\a`. A sound (b) is an allowlist: `\` + `[1-9]\d?`, `\g<...>`,
  `\\`, and everything else rejected.
- **(b) keeps the preview lying.** `\1` would substitute live while the only rendered M3U-profile
  preview shows `\1` literally. Fixing that means teaching `applyRegex` Python's reading — a frontend
  change and a second grammar in the SPA.

(b) is a legitimate ruling if keeping existing rename templates working outweighs one grammar; its
cost is bounded in § If the user rules for the alternative.

### Sub-questions and their defaults

"Full JavaScript semantics" raises five more tokens. The rule: include only what the backslash change
makes inseparable; everything else is a follow-up with a reason, so the implementer never widens scope.

| token | seed Python | JavaScript | default here | why |
|---|---|---|---|---|
| `$$` | `$$` | `$` | **out** (#371) | Separable: the doubling emits no `$`, and #371's own fix direction (`$$` → `$` then `$&` → `\g<0>`) composes with it unchanged, provided #371 does it in one tokenizing pass so `$$1` stays `$1` (seed gives `$a`, JS `$1`). |
| `$&` | `$&` | whole match | **out** (#371) | Same function, same follow-up. |
| `` $` ``, `$'` | literal | pre-/post-match | **out** | No issue yet; fold into #371 (§ Follow-ups item 2). |
| `$10` on two groups | `regex.error: invalid group reference` → caller's fallback | group 1 then `0` | **out** | Pre-existing and recorded by #440; the fallback depends on the pattern's group count, which a template rewrite cannot see. Needs a callable replacement instead of a template — an architecture change. |
| `$<name>`, group missing | URL paths: `IndexError`, caught by `except Exception` at all three URL sites (`next_source.py:308`, `vod_proxy/views.py:644`, `tasks.py:3185`) → original URL / base credentials; rename paths: never rewritten, literal | literal `$<x>` if the regex has no named groups, else `""` | **out** for the URL paths; **falls out** for the rename paths | URL paths already fall back rather than crash; the divergence is output, not a 500, and is a follow-up. On the rename paths the `IndexError` the issue names is reachable today only as `\g<name>`, and under (a) `\g<name>` is literal text, so it becomes unreachable with no extra code — pinned by `test_rename_preview_backslash_named_group_is_literal_not_a_500` (red at seed with `IndexError: unknown group`). |

### Test design

- New module `apps/m3u/tests/test_replace_template_backslash.py` (Appendix B):
  - `HelperBackslashTests.test_backslash_zero_is_literal_not_a_nul_byte`.
  - `HelperBackslashTests.test_backslash_sequences_read_exactly_as_javascript_does` — one subTest per
    row of `NODE_BACKSLASH_OUTPUTS`, fourteen templates, expected values recorded from Node v22.14.0
    (a table of constants; the oracle never calls the helper).
  - `GetTransformedCredentialsBackslashTests` — `\0-X` yields the literal username `\0-X` (path 3), and
    `$<u>2` still substitutes (the ordering guard for path 3; green at seed, red under BC-3).
  - `RenameBackslashTests` — the real `sync_auto_channels` writes `[\0]Alpha Channel` (path 4; red at
    seed with the NUL abort above), and the real preview endpoint answers 200 with `\g<x> Channel` for
    `\g<x>` (path 5; red at seed with `IndexError`).
  - The module imports only `convert_js_numbered_backreferences`, which exists at seed, so its red
    run at seed names the mechanism rather than an `ImportError` (the true-positive-for-a-false-reason
    trap).
- `apps/proxy/tests/test_next_source_edges.py` gains class `TransformUrlBackslashTests` (path 1): `\0`
  literal, four Node rows, and `$<host>` / `\$<host>` (the ordering guard for path 1).
- `apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py` gains two methods (path 2): `\0`
  literal, and `$<host>2` (the ordering guard for path 2; green at seed, red under BC-2).
- `apps/m3u/tests/test_property_backreferences.py` widens both template alphabets to the backslash and
  adds one `@example` (`[\0]` on `(a)`), per its own docstring. Measured load-bearing: with the seed
  alphabet and the doubling deleted, the module is **green** (`Ran 3 tests … OK`); with the widened
  alphabet and the doubling deleted, both properties fail (Task 1's expected output).

### If the user rules for the alternative (b)

Only these parts change; everything not named stays as written.

- **Appendix A, `apps/m3u/utils.py` hunk:** replace the doubling line in `_js_template_to_python`
  (`template = replacement.replace("\\", "\\\\")`) with an allowlist check that raises
  `regex.error` for any backslash not followed by `[1-9]\d?`, `g<...>` or a second backslash. The three
  URL-site hunks and the `tasks.py` import hunk are unchanged (the sites still call one function; with
  no doubling the call order no longer matters, but the single call stays).
- **Two new production hunks** this plan does not carry: the same check in
  `M3UAccountProfileSerializer.validate` **above** the default-profile early return
  (`apps/m3u/serializers.py:77-80`), and in `update_group_settings`'s validation loop
  (`apps/m3u/api_views.py:487-511`), each a 400 naming the field. Each needs a new test, and
  `apps/m3u/api_views.py` routes to `apps.m3u.tests` only (no new label).
- **Appendix B expected values:** `NODE_BACKSLASH_OUTPUTS` is no longer a Node table. It becomes an
  accept/reject table: `[\1]` → `[a]`, `[\g<1>]` → `[a]`, `[\\]` → `[\]`, `[\$1]` → `[\g<1>]`
  (unchanged from seed), and `[\0]`, `[\x01]`, `[\n]`, `[\t]`, `[\u0041]`, `[\N{DIGIT ONE}]`, `[\q]`,
  `C:\path\$1` → rejected (`regex.error`). The test is renamed
  `test_backslash_sequences_follow_the_documented_hybrid_grammar`. The credential test expects the base
  username (`myuser`, the fallback), not `\0-X`. The rename-sync test expects the original name
  `Alpha Channel` and status `ok`; the preview test expects `find_error` set and status 200. The
  next-source and VOD `\0` tests expect the original URL.
- **Property module:** property 1's alphabet widens as planned (a rejected template returns `None` and
  is skipped). Property 2's `js_templates` alphabet stays backslash-free: its model is JavaScript, and
  under (b) `\1` is not JavaScript. Its docstring then records (b) as the reason.
- **BC-1** becomes: let the allowlist also accept `\a`; property 1 should redden with an
  `AssertionError:` line containing `not less than or equal to` and ending `: '\x07'` (the two set reprs' element order varies per
  process; see Task 1's note). That line was measured under
  this plan's BC-1 (the denylist, which leaves `\a` unrejected the same way); it was **not** re-measured
  under a (b) implementation, which does not exist yet. BC-2 and BC-3 are unchanged.
- **Migration note:** instead of "rewrite `\1` as `$1`", it lists the rejected escapes, and states that
  a stored template carrying one falls back (URL unchanged, name unchanged) until edited.
- **Not closed by (b):** the M3U-profile preview still shows `\1` literally while the stream
  substitutes group 1; list that as a frontend follow-up.

---

## PR: `fix/452-replace-template-backslash`

- **Issue** #452 (planned here). The implementation PR's body carries `<closing keyword> #452.` (Global constraint 8).
- **Files.**
  - Production (Appendix A): `apps/m3u/utils.py` (new private `_js_template_to_python`, new public
    `convert_js_replacement_template`, `convert_js_numbered_backreferences` rewritten onto the private
    one); `apps/proxy/next_source.py` (`:31` import, `:287-290` → one call); `apps/proxy/vod_proxy/views.py`
    (`:626` import, `:633-635` → one call); `apps/m3u/tasks.py` (`:34` import added, `:3117-3120` → one
    call). The rename call sites `apps/m3u/tasks.py:2631` and `apps/channels/api_views.py:404` are
    **unchanged**; they change behaviour through the helper.
  - Tests (Appendix B): new `apps/m3u/tests/test_replace_template_backslash.py`; modified
    `apps/m3u/tests/test_property_backreferences.py`; appended to
    `apps/proxy/tests/test_next_source_edges.py` and
    `apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py`.
- **Labels.** `python scripts/ci_backend_test_labels.py <the eight paths>` prints
  `["apps.m3u.tests", "apps.proxy.tests", "apps.proxy.vod_proxy.tests"]`. Three labels, one PR: splitting
  the URL sites from the helper would leave a merged state in which the helper doubles backslashes and
  a site still rewrites `$<name>` before calling it, which escapes every named group into literal text
  (BC-2 is exactly that state). C-4 landed all its sites together for the same reason. Also run `tests`
  (for `tests/test_websocket_consumer_filter.py`, which drives `transform_url` through the WebSocket
  preview) and `apps.channels.tests` (owner of the rename preview) locally; neither is routed, both
  must stay green.
- **Gate 2.** `apps/proxy/next_source.py` is `scripts/coverage_live_path.coveragerc:44`. The edit
  replaces two statements with one and changes one import. Measured on the export with Appendix A+B
  applied, in two private containers:
  `coverage_live_path: floor missing=33  this run missing=33  coverage 97.46%`, denominator 1301
  (informational). `missing` must stay 33.
- **Upstreamable.** No: `apps/proxy/next_source.py` is fork-only (upstream's copy lives in
  `apps/proxy/live_proxy/`), and #440, which this builds on, is fork-only.

### Tasks

**Task 0 — branch and container.**

- [ ] `cd /Users/dion/git/Dispatcharr && git fetch origin && git worktree add .worktrees/fix-452 -b fix/452-replace-template-backslash origin/main`
- [ ] `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git merge-base --is-ancestor 36e4ce10 HEAD && echo ok` prints `ok`.
      Then, bare: `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git diff --stat 36e4ce10 HEAD -- apps/m3u/utils.py apps/m3u/tasks.py apps/proxy/next_source.py apps/proxy/vod_proxy/views.py apps/m3u/tests/test_property_backreferences.py apps/proxy/tests/test_next_source_edges.py apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py apps/channels/api_views.py`.
      Empty is the pass. If any of these files moved since the seed, the appendices may not apply: STOP and report.
- [ ] Start the private container (Global constraint 6) with `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/fix-452`.

**Task 1 — tests first, red at the seed.**

- [ ] Extract Appendix B (§ Appendix extraction) to `/tmp/452-B.diff` and check its SHA-256.
- [ ] `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git apply /tmp/452-B.diff && git status --short`
      shows three `M` files and one `??` file.
- [ ] Run, in one command:
      `apps.m3u.tests.test_replace_template_backslash apps.proxy.tests.test_next_source_edges.TransformUrlBackslashTests apps.proxy.vod_proxy.tests.test_transform_url_backreferences apps.m3u.tests.test_property_backreferences`.
      Expected (measured at the seed): `Ran 15 tests`, `FAILED (failures=21, errors=5)`. The failures
      must name the mechanism; check for these lines verbatim (`grep -a`):
      - `AssertionError: '[\x00]' != '[\\0]'` (helper, NUL)
      - `AssertionError: '[a]' != '[\\1]'` (helper and `transform_url`, `\1` read as group 1)
      - `AssertionError: '\x00-X' != '\\0-X'` (credentials)
      - `'error': 'PostgreSQL text fields cannot contain NUL (0x00) bytes'` inside the
        `AssertionError: 'error' != 'ok'` message (rename sync)
      - `IndexError: unknown group` (rename preview and the `[\g<x>]` subTest)
      - `AssertionError: 'http://[\x00]host/p' != 'http://[\\0]host/p'` (twice: `transform_url`, VOD)
      - `AssertionError: 'http://\\g<host>/p' != 'http://\\host/p'` (`transform_url`'s second named-group assertion)
      - property 1, the new `@example`: an `AssertionError:` line containing `not less than or equal to`
        and ending `: '[\x00]'`. The two sets in that line (one measured run printed
        `{'\x00', '[', ']'}` and `{'[', ']', '0', '\\', 'a'}`) are Python set reprs, whose element order
        changes with per-process string-hash randomisation, so match only the stable part:
        `grep -aE "not less than or equal to .* : '\[\\\\x00\]'$" <log>`.
      - `AssertionError: 'a\x00' != 'a\\0'` inside `Hypothesis found 2 distinct failures` (property 2)
      Any `ImportError`, `NameError` or `SyntaxError` is a STOP. The three ordering guards
      (`test_vod_transform_named_group_still_substitutes`,
      `test_get_transformed_credentials_named_group_still_substitutes` and the first assertion of
      `test_transform_url_named_group_still_substitutes`) are **green** at seed by design: they pin
      behaviour this PR must preserve, and BC-2/BC-3 prove they can fail.

**Task 2 — the fix.**

- [ ] Extract Appendix A to `/tmp/452-A.diff`, check its SHA-256, and
      `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git apply /tmp/452-A.diff`.
- [ ] Re-run Task 1's command: `Ran 15 tests`, `OK`.

**Task 3 — commit.**

- [ ] `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git add apps/m3u/utils.py apps/m3u/tasks.py apps/proxy/next_source.py apps/proxy/vod_proxy/views.py apps/m3u/tests/test_replace_template_backslash.py apps/m3u/tests/test_property_backreferences.py apps/proxy/tests/test_next_source_edges.py apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py`
- [ ] In a separate Bash call, `git commit -F <message file>` (written with the Write tool; subject
      `fix(m3u,proxy): a backslash in a replace template is literal text, as in JavaScript (#452)`, body
      = the migration note, then `<closing keyword> #452.`, then the attribution line). The commit gate runs the
      three routed labels; it must pass.

**Task 4 — break-checks, against the Task 3 commit.** Make each edit by hand, run, confirm the
verbatim red line, then `git checkout -- <file>` and confirm `git status --short` is empty before the
next one.

- [ ] **BC-1 (a denylist, the shape option (b) invites).** In `apps/m3u/utils.py`, replace
      `    template = replacement.replace("\\", "\\\\")` with
      `    template = regex.sub(r"\\(?=[0xnNtuU])", r"\\\\", replacement)`.
      Run `apps.m3u.tests.test_replace_template_backslash.HelperBackslashTests apps.m3u.tests.test_property_backreferences apps.proxy.tests.test_next_source_edges.TransformUrlBackslashTests`.
      Expected: `Ran 8 tests`, `FAILED (failures=9, errors=4)`, including
      `AssertionError: '[a]' != '[\\1]'` (subTest `template='[\\1]'`) and
      property 1's `AssertionError:` line containing `not less than or equal to` and ending `: '\x07'`
      (it finds `\a`, a BEL byte, that the denylist forgot; set order varies per process, as in Task 1:
      `grep -aE "not less than or equal to .* : '\\\\x07'$" <log>`). `git checkout -- apps/m3u/utils.py`.
- [ ] **BC-2 (a URL site keeps the seed call order).** In `apps/proxy/vod_proxy/views.py`, restore the
      seed's two lines in place of the one call, and the seed import:
      `from apps.m3u.utils import convert_js_numbered_backreferences`, then
      `safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', replace_pattern)` and
      `safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)`.
      Run `apps.proxy.vod_proxy.tests`. Expected: exactly one failure,
      `test_vod_transform_named_group_still_substitutes`, with
      `AssertionError: 'http://\\g<host>2/p' != 'http://host2/p'` (the doubling escaped the `\g<host>`
      the earlier rewrite produced). `git checkout -- apps/proxy/vod_proxy/views.py`.
- [ ] **BC-3 (the same, credentials).** In `apps/m3u/tasks.py`, replace the one
      `convert_js_replacement_template(profile.replace_pattern)` line with the seed's
      `safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', profile.replace_pattern)` followed
      by `safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)`.
      Run `apps.m3u.tests.test_replace_template_backslash apps.m3u.tests.test_js_backreference_conversion apps.m3u.tests.test_xc_live_url`.
      Expected: `Ran 26 tests`, `FAILED (failures=1)`:
      `test_get_transformed_credentials_named_group_still_substitutes` with
      `AssertionError: '\\g<u>2' != 'myuser2'`. `git checkout -- apps/m3u/tasks.py`.
- [ ] `git status --short` is empty after the three reverts.

**Task 5 — full labels and Gate 2.**

- [ ] Flush Redis and run each of `apps.m3u.tests`, `apps.proxy.tests`, `apps.proxy.vod_proxy.tests`,
      `tests`, `apps.channels.tests` separately, fresh DB (Global constraint 6). Measured on the seed plus
      this PR: 251, 401, 94, 168 and 365 tests, all `OK` (the seed's own counts are 245, 398, 92, 168,
      365: this PR adds 6, 3 and 2). A later base may add tests; any failure is a STOP.
- [ ] Gate 2, with two private containers mounted at your worktree:
      ```bash
      for s in proxy channels; do DISPATCHARR_TEST_CONTAINER=fix-452-cov-$s DISPATCHARR_TEST_DB_VOLUME=fix-452-cov-$s-db CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/fix-452 /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh; done
      cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && COVERAGE_ISOLATED_PREFIX=fix-452-cov bash scripts/coverage_live_path_isolated.sh --gate; echo "exit=$?"
      ```
      Expected: `labels: proxy=0 channels=0`, `floor missing=33  this run missing=33`, `exit=0`. Then
      `docker rm -f fix-452-cov-proxy fix-452-cov-channels; docker volume rm fix-452-cov-proxy-db fix-452-cov-channels-db`.
- [ ] `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && python3 scripts/check_credential_logging.py apps/m3u/utils.py apps/m3u/tasks.py apps/proxy/next_source.py apps/proxy/vod_proxy/views.py apps/m3u/tests/test_replace_template_backslash.py; echo "exit=$?"` prints `exit=0`.

**Task 6 — push and PR.**

- [ ] `cd /Users/dion/git/Dispatcharr/.worktrees/fix-452 && git push -u origin fix/452-replace-template-backslash`
- [ ] Open the PR with § PR description draft, filling the `<paste>` slots from Tasks 4-5:
      `gh pr create --repo D10Scot/Dispatcharr --base main --title "fix(m3u,proxy): a backslash in a replace template is literal text, as in JavaScript (#452)" --body-file <file>`.
- [ ] `docker rm -f fix-452; docker volume rm fix-452-db`.

### Existing tests that must stay green unmodified

- `apps/m3u/tests/test_js_backreference_conversion.py` (all of it: the #171 table, `$0` literal,
  `$02-$01`, the credentials `$0-X` test).
- `apps/m3u/tests/test_rename_preview_parity.py` — every `STRATEGIES` row is backslash-free in the
  **template** (the backslashes in that table are in the find patterns), so the rewrite is byte-identical
  for all of them; `(r"(.+)", r"$2")` and `(r"(.+)", r"$10")` still fail on both paths.
- `apps/m3u/tests/test_xc_live_url.py` (`$1` templates through `get_transformed_credentials`).
- `apps/m3u/tests/test_sync_correctness.py` (`$1` and `$` rename templates, `:814-913`).
- `apps/proxy/tests/test_next_source_edges.py`: `TransformUrlNoMatchTests`, `TransformUrlBackreferenceTests`.
- `apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py`:
  `test_vod_transform_dollar_zero_does_not_inject_nul_bytes`.
- `tests/test_websocket_consumer_filter.py:271-340` (ReDoS and rewrite through the WebSocket preview;
  its template `$1/newuser/newpass/$4` at `:332` is backslash-free).
- The whole of `apps.channels.tests`.

### Existing tests deliberately changed

One module, `apps/m3u/tests/test_property_backreferences.py`. No assertion line changes; the input
domain widens, and one `@example` is added. Every line (Appendix B, second file):

| where (seed) | before | after |
|---|---|---|
| docstring `:15-19` | "Generated templates exclude the backslash … The alphabet widens to include the backslash once #452 is ruled." | "Before #452, a backslash in the template reached Python's replacement-template parser, so `\0` was a NUL byte too; the helper now doubles every backslash first, as JavaScript treats it as literal text, and generated templates include the backslash." |
| comment `:73-77` | "… but no backslash … the alphabet widens once #452 is ruled." | "… `$` and the backslash, which JavaScript keeps as literal text (#452)." |
| `:78` `templates` | `alphabet="ab/-[]$0123456789x"` | `alphabet="ab/-[]$0123456789x\\"` |
| `:104` `js_templates` first char | `st.sampled_from("ab/-[]x")` | `st.sampled_from("ab/-[]x\\")` |
| `:105` `js_templates` rest | `alphabet="ab/-[]x0123456789"` | `alphabet="ab/-[]x0123456789\\"` |
| after `:155` | two `@example`s | a third: `@example(case=(r"(a)", 1), data=None)` with comment `# #452: "[\0]" reached the template parser as a NUL byte.` |
| `:161` comment, `:163-166` dict | two #171 rows | "The #171 and #452 regressions above", plus `(r"(a)", 1): (r"[\0]", "a")` |

Why it is the behaviour being changed: property 1 ("no character absent from target and template") and
property 2 (equals the JavaScript model) excluded the backslash **only** because of #452, as the module
says of itself; the widened module is red at seed and green after (Task 1/2), and green at seed with
the old alphabet (measured), so the old alphabet could not see the defect.

### Migration note (operator-facing)

No `docs/` page documents the template grammar, and the fork has never edited `CHANGELOG.md` (its
last commits are upstream's, up to `d9abece0` "Release v0.29.0"; `release.yml` publishes with
`--notes ""`). The note therefore goes in the PR description and the squash commit body, verbatim:

> **Breaking for templates that contain a backslash.** In an M3U profile's Replace pattern and an
> auto-sync group's rename Replace, a backslash is now literal text, as in JavaScript and as the
> M3U-profile form's own preview already showed. Use `$1`…`$99` for capture groups (and `$<name>` for
> named groups in M3U profiles) instead of `\1` or `\g<1>`. Before this change `\0` inserted a NUL
> byte into the stream URL or channel name (and a NUL in a rename aborted the whole account's
> auto-sync), and `\1` was group 1. Templates without a backslash behave exactly as before. To find
> affected rows: [the two queries from § Ruling].

The SPA help text (`M3UProfile.jsx:309`, `:369`: "Use $1, $2, etc.") is already correct under (a) and is
not changed (Global constraint 11).

### PR description draft

> **fix(m3u,proxy): a backslash in a replace template is literal text, as in JavaScript (#452)**
>
> #440 made `$0`/`$01` safe by adopting JavaScript's `$n` grammar; the same corruption was still
> reachable through a backslash, which every path through the shared helper handed to Python's
> replacement-template parser: `\0` put a NUL byte into live and VOD stream URLs, XC credentials and
> channel names (and a NUL in a rename aborted the whole account's auto-sync with "PostgreSQL text
> fields cannot contain NUL (0x00) bytes"), `\x01`/`\n`/`\a` put control bytes there, `\1` was
> group 1, and `\g<x>` 500'd the rename preview. The helper now doubles every backslash **before** it
> rewrites `$<name>` and `$n`, so a backslash is literal on all five paths — which is what the only
> rendered M3U-profile preview (`applyRegex`, JavaScript) already showed. The three URL sites call one
> new function, `convert_js_replacement_template`, instead of rewriting `$<name>` themselves first,
> because that order would now escape the `\g<name>` they produce. A template without a backslash is
> rewritten byte-for-byte as before.
>
> Grammar ruling: <paste the user's ruling on #452, or "planner's default (a); no user ruling">.
>
> <migration note, verbatim>
>
> Not touched: `$$`, `$&` (#371), `` $` ``/`$'`, JavaScript's `$10`-on-two-groups fallback, the
> bulk-rename rule `translate_js_replacement` (#372), the SPA.
>
> Gate 2: <paste `floor missing=… this run missing=…`>. Break-checks: <paste BC-1..BC-3 lines>.
> Tests run (fresh DB, own container): <paste the five label counts>. Existing test changed: the
> property module's template alphabets widen to the backslash, as its docstring anticipated; no
> assertion changed.
>
> <closing keyword> #452.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Metrics

None. `grep -rn 452 metrics/curated/` exits 1 at seed (Global constraint 9). The implementation PR
touches nothing under `metrics/`; `python -m metrics.build --validate-only` is not required by this PR
and need not be run.

## Follow-ups

Named here and excluded, one line each. None is filed by this plan.

1. **`$$` and `$&` (#371).** Separable; must be one tokenizing pass so `$$1` reads `$1`, and composes
   with the doubling unchanged.
2. **`` $` `` and `$'`** stay literal where JavaScript substitutes pre-/post-match; no issue; fold into #371.
3. **`$10` with two groups** raises and falls back where JavaScript emits group 1 then `0`; needs a
   callable replacement that knows the group count.
4. **`$<name>` divergences.** URL paths: a missing group falls back (caught) where JavaScript emits text;
   rename paths never honour `$<name>` at all. Both pre-existing output divergences, not crashes.
5. **Bulk rename `translate_js_replacement`** (`apps/channels/api_views.py:1552-1561`) has the same
   backslash defect, measured: `[\0]` → `'[\x00]'`, `[\1]` → `'[a]'`. Out because it is a separate
   grammar (`$0` as whole match, its own `$$`/`$&`) already tracked as #372; fold the backslash into #372
   and give it the shared helper.
6. **A data migration rewriting stored `\N` templates** is rejected: the translation is lossy (`\\`,
   `\n`, `\12` vs `$12` differ in meaning) and silent; the migration note's query finds the rows instead.
7. **SPA help text** could say "a backslash is literal"; frontend-only, optional.
8. **The WebSocket `m3u_profile_test` result is never rendered** (`profileResult` has no reader,
   `frontend/src/store/playlists.jsx:12`); dead end-to-end, separate cleanup.

## Appendix extraction

Each appendix is one fenced `diff` block between an HTML comment marker pair. Extract, check, apply:

```bash
set -o pipefail
PLAN=/Users/dion/git/Dispatcharr/docs/superpowers/plans/2026-09-25-fix-452-replace-template-backslash.md  # or your checkout's copy
for X in A B; do
  awk -v b="<!-- BEGIN APPENDIX $X -->" -v e="<!-- END APPENDIX $X -->" \
    '$0==b{f=1;next} $0==e{f=0} f' "$PLAN" | sed '1d;$d' > /tmp/452-$X.diff
done
shasum -a 256 /tmp/452-A.diff /tmp/452-B.diff
```

Expected: `bf14fbe3c0b587081229bc235e79909532f710947e351db9177df227c9039434` for A and `7f8ddd9101fcd8b4df6226c3400da2ec8e6f48fb502291e26875a9a043edb097` for B. Both were checked with
`git apply --check` against `36e4ce10`.

## Appendix A — production hunks against `36e4ce10`

Verified: applied with Appendix B to a `git archive 36e4ce10` export, run in private container
`plan-452` (image `ghcr.io/d10scot/dispatcharr:latest`, fresh DB): `apps.m3u.tests` 251 OK,
`apps.proxy.tests` 401 OK, `apps.proxy.vod_proxy.tests` 94 OK, `tests` 168 OK, `apps.channels.tests`
365 OK; Gate 2 `missing=33`.

<!-- BEGIN APPENDIX A -->
```diff
diff --git a/apps/m3u/tasks.py b/apps/m3u/tasks.py
index 6788247..0592a99 100644
--- a/apps/m3u/tasks.py
+++ b/apps/m3u/tasks.py
@@ -32,6 +32,7 @@ from dispatcharr.utils import redact_headers, redact_url
 from .utils import (
     _BoundedFilterPattern,
     convert_js_numbered_backreferences,
+    convert_js_replacement_template,
     normalize_stream_url,
     parse_is_adult,
 )
@@ -3114,10 +3115,10 @@ def get_transformed_credentials(account, profile=None):
         # Apply profile-specific transformations if profile is provided
         if profile and profile.search_pattern and profile.replace_pattern:
             try:
-                # Handle backreferences: convert JS-style $<name> -> \g<name>, $1 -> \g<1>
-                # regex module accepts JS-style (?<name>...) named groups natively
-                safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', profile.replace_pattern)
-                safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)
+                # Convert the JS-style template: a backslash is literal (#452),
+                # then $<name> -> \g<name>, $1 -> \g<1>. The regex module
+                # accepts JS-style (?<name>...) named groups natively.
+                safe_replace_pattern = convert_js_replacement_template(profile.replace_pattern)
 
                 # Apply transformation to the complete URL
                 transformed_complete_url = regex.sub(profile.search_pattern, safe_replace_pattern, complete_url)
diff --git a/apps/m3u/utils.py b/apps/m3u/utils.py
index 4f6eb3d..0ff73f6 100644
--- a/apps/m3u/utils.py
+++ b/apps/m3u/utils.py
@@ -78,8 +78,25 @@ def m3u_cp1252_fallback(error):
 codecs.register_error("m3u_cp1252_fallback", m3u_cp1252_fallback)
 
 
+def _js_template_to_python(replacement, named_groups):
+    """Rewrite a JavaScript replacement template for Python's ``regex.sub``.
+
+    Order matters. Every backslash is doubled FIRST (#452): in JavaScript a
+    backslash in a replacement template is literal text, while Python's
+    template parser reads it as an escape -- ``\\0`` was a NUL byte,
+    ``\\x01`` a control byte and ``\\1`` group 1. The ``$<name>`` and ``$n``
+    rewrites run afterwards, so the ``\\g<...>`` they emit is never itself
+    escaped into literal text. A template with no backslash is rewritten
+    exactly as before.
+    """
+    template = replacement.replace("\\", "\\\\")
+    if named_groups:
+        template = regex.sub(r"\$<([^>]+)>", r"\\g<\1>", template)
+    return regex.sub(r"\$(0[1-9]|[1-9]\d?)", r"\\g<\1>", template)
+
+
 def convert_js_numbered_backreferences(replacement):
-    """Translate JS-style ``$1``/``$01`` backreferences to Python ``\\g<N>``.
+    """Translate a JS-style replacement template to a Python ``regex`` one.
 
     Auto-sync replace patterns are authored in JS regex syntax, but Python's
     regex engines honor backslash backreferences, not ``$1``. The live rename
@@ -87,6 +104,12 @@ def convert_js_numbered_backreferences(replacement):
     helper and cannot drift apart (otherwise the preview promises an output
     the sync would never produce).
 
+    A backslash is literal text, as in JavaScript (#452): ``\\1`` is the two
+    characters ``\\`` and ``1``, never group 1, and ``\\0`` is never a NUL
+    byte. ``$`` followed by ``<`` is not rewritten here; the URL transforms
+    use :func:`convert_js_replacement_template`, which also honours
+    ``$<name>``.
+
     The token grammar is JavaScript's own ``$n``/``$nn`` (#171): exactly two
     digits ``01``-``99``, or one digit ``1``-``9``, and nothing longer. A
     bare ``$0`` (and ``$00``, ``$001``, ...) is therefore never a token and
@@ -99,7 +122,18 @@ def convert_js_numbered_backreferences(replacement):
     than ``\\N``) is used so a two-digit group number is never misread as a
     one-digit group followed by a literal digit.
     """
-    return regex.sub(r"\$(0[1-9]|[1-9]\d?)", r"\\g<\1>", replacement)
+    return _js_template_to_python(replacement, named_groups=False)
+
+
+def convert_js_replacement_template(replacement):
+    """The URL-transform grammar: :func:`convert_js_numbered_backreferences`
+    plus ``$<name>`` -> ``\\g<name>``.
+
+    Used by the three M3U-profile URL transforms (``transform_url``, the VOD
+    ``_transform_url`` and ``get_transformed_credentials``), which honour
+    named groups; the auto-sync rename and its preview never have.
+    """
+    return _js_template_to_python(replacement, named_groups=True)
 
 
 def parse_is_adult(value):
diff --git a/apps/proxy/next_source.py b/apps/proxy/next_source.py
index de3276f..b26aa24 100644
--- a/apps/proxy/next_source.py
+++ b/apps/proxy/next_source.py
@@ -28,7 +28,7 @@ from apps.m3u.connection_pool import (
     profile_available_for_channel_switch,
 )
 from apps.m3u.models import M3UAccount, M3UAccountProfile
-from apps.m3u.utils import convert_js_numbered_backreferences
+from apps.m3u.utils import convert_js_replacement_template
 from core.models import StreamProfile
 from dispatcharr.utils import redact_url
 
@@ -284,10 +284,10 @@ def transform_url(input_url: str, search_pattern: str, replace_pattern: str) ->
         logger.debug(f"  base URL: {redact_url(input_url)}")
         logger.debug(f"  search: {search_pattern}")
 
-        # Convert JS-style backreferences in replace pattern: $<name> -> \g<name>, $1 -> \g<1>
-        # Fixed conversion patterns only; timeout is reserved for the user search.
-        safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', replace_pattern)
-        safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)
+        # Convert the JS-style template: a backslash is literal (#452), then
+        # $<name> -> \g<name>, $1 -> \g<1>. Fixed conversion patterns only;
+        # the timeout is reserved for the user search.
+        safe_replace_pattern = convert_js_replacement_template(replace_pattern)
         logger.debug(f"  replace: {replace_pattern}")
         logger.debug(f"  safe replace: {safe_replace_pattern}")
 
diff --git a/apps/proxy/vod_proxy/views.py b/apps/proxy/vod_proxy/views.py
index 32e3bc6..782bc63 100644
--- a/apps/proxy/vod_proxy/views.py
+++ b/apps/proxy/vod_proxy/views.py
@@ -623,16 +623,16 @@ def _transform_url(original_url, m3u_profile):
     try:
         import regex
 
-        from apps.m3u.utils import convert_js_numbered_backreferences
+        from apps.m3u.utils import convert_js_replacement_template
 
         if not original_url:
             return None
 
         search_pattern = m3u_profile.search_pattern
         replace_pattern = m3u_profile.replace_pattern
-        # Convert JS-style backreferences in replace: $<name> -> \g<name>, $1 -> \g<1>
-        safe_replace_pattern = regex.sub(r'\$<([^>]+)>', r'\\g<\1>', replace_pattern)
-        safe_replace_pattern = convert_js_numbered_backreferences(safe_replace_pattern)
+        # Convert the JS-style template: a backslash is literal (#452), then
+        # $<name> -> \g<name>, $1 -> \g<1>.
+        safe_replace_pattern = convert_js_replacement_template(replace_pattern)
 
         if search_pattern and replace_pattern:
             # regex module accepts JS-style (?<name>...) named groups natively
```
<!-- END APPENDIX A -->

## Appendix B — test hunks against `36e4ce10`

Verified: applied alone to the same export, red as Task 1 states (`Ran 15 tests`,
`FAILED (failures=21, errors=5)`); with Appendix A, green as Appendix A states; break-checks BC-1..BC-3
red as Task 4 states.

<!-- BEGIN APPENDIX B -->
```diff
diff --git a/apps/m3u/tests/test_property_backreferences.py b/apps/m3u/tests/test_property_backreferences.py
index 248baf6..0f1ec33 100644
--- a/apps/m3u/tests/test_property_backreferences.py
+++ b/apps/m3u/tests/test_property_backreferences.py
@@ -12,11 +12,10 @@ reading:
 
 1. The output contains no character that is in neither the target nor the
    template. Before C-4, ``$0`` became ``\0`` (a NUL byte) and ``$01`` became
-   ``\01`` (U+0001). Generated templates exclude the backslash: the helper
-   hands a backslash straight to Python's replacement-template parser, which
-   JavaScript never does, so a template containing one reopens exactly this
-   symptom (#452). The alphabet widens to include the backslash once #452 is
-   ruled.
+   ``\01`` (U+0001). Before #452, a backslash in the template reached Python's
+   replacement-template parser, so ``\0`` was a NUL byte too; the helper now
+   doubles every backslash first, as JavaScript treats it as literal text, and
+   generated templates include the backslash.
 2. For templates whose tokens are ``$N`` or ``$0N`` with 1 <= N <= the group
    count, and whose next literal character is not a digit, the output equals
    a hand-written model of JavaScript's ``String.prototype.replace`` with a
@@ -70,12 +69,9 @@ PATTERNS = [
     (r"([a-z]+)-(\d+)?", 2),
 ]
 targets = st.text(alphabet="abhu/-0123456789xy", max_size=24)
-# Templates as the operator types them: literals, digits and ``$``, but no
-# backslash. The helper hands a backslash straight to Python's replacement-
-# template parser, which JavaScript never does, so a template containing one
-# reopens #171's corrupted-output symptom (#452); the alphabet widens once
-# #452 is ruled.
-templates = st.text(alphabet="ab/-[]$0123456789x", max_size=16)
+# Templates as the operator types them: literals, digits, ``$`` and the
+# backslash, which JavaScript keeps as literal text (#452).
+templates = st.text(alphabet="ab/-[]$0123456789x\\", max_size=16)
 
 
 def _apply(pattern, template, target):
@@ -101,8 +97,8 @@ def js_templates(draw, group_count):
             zero = draw(st.sampled_from(("", "0")))
             pieces.append(("group", n, f"${zero}{n}"))
         else:
-            first = draw(st.sampled_from("ab/-[]x"))
-            rest = draw(st.text(alphabet="ab/-[]x0123456789", max_size=4))
+            first = draw(st.sampled_from("ab/-[]x\\"))
+            rest = draw(st.text(alphabet="ab/-[]x0123456789\\", max_size=4))
             pieces.append(("literal", None, first + rest))
     return pieces
 
@@ -153,16 +149,19 @@ class JsBackreferenceConversionProperties(SimpleTestCase):
     @example(case=(r"(.*)$", 1), data=None)
     # #171: "$01" became "\01", a U+0001 control byte.
     @example(case=(r"(h)/(u)", 2), data=None)
+    # #452: "[\0]" reached the template parser as a NUL byte.
+    @example(case=(r"(a)", 1), data=None)
     def test_conversion_never_introduces_a_character_absent_from_target_and_template(
         self, case, data
     ):
         pattern, group_count = case
         if data is None:
-            # The two #171 regressions above: literal templates the free-form
+            # The #171 and #452 regressions above: literal templates the free-form
             # strategy is unlikely to draw unaided.
             template, target = {
                 (r"(.*)$", 1): ("$0", "/"),
                 (r"(h)/(u)", 2): ("$01/$2", "http://h/u/p/1.ts"),
+                (r"(a)", 1): (r"[\0]", "a"),
             }[case]
         elif data.draw(st.booleans()):
             pieces = data.draw(js_templates(group_count))
diff --git a/apps/m3u/tests/test_replace_template_backslash.py b/apps/m3u/tests/test_replace_template_backslash.py
new file mode 100644
index 0000000..ee94fe3
--- /dev/null
+++ b/apps/m3u/tests/test_replace_template_backslash.py
@@ -0,0 +1,170 @@
+r"""#452: a backslash in an M3U replace template is literal text, as in JavaScript.
+
+Replace templates are authored in JavaScript's replacement syntax, and the
+only rendered M3U-profile preview evaluates them with
+``String.prototype.replace`` (``frontend/src/utils/forms/M3uProfileUtils.js``,
+``applyRegex``), where a backslash has no special meaning. Python's
+replacement-template parser reads the same backslash as an escape: before
+#452, ``\0`` became a NUL byte, ``\x01`` a control byte, ``\n`` a newline and
+``\1`` group 1 in every path through the shared helper -- the live and VOD URL
+transforms, the XC credential transform, and the auto-sync rename and its
+preview. The helper now doubles every backslash before it rewrites ``$n``
+(and, for the three URL paths, ``$<name>``), so the backslash reaches the
+engine as a literal.
+
+Every expected value below was recorded from Node 22.14.0 as
+``target.replace(new RegExp(pattern, "g"), template)``; none is computed by
+the code under test.
+"""
+import regex
+from django.test import SimpleTestCase, TestCase
+from django.utils import timezone
+
+from apps.channels.models import (
+    Channel,
+    ChannelGroup,
+    ChannelGroupM3UAccount,
+    Stream,
+)
+from apps.m3u.models import M3UAccount
+from apps.m3u.tasks import get_transformed_credentials, sync_auto_channels
+from apps.m3u.utils import convert_js_numbered_backreferences
+
+# (template, "a".replace(/(a)/g, template) in Node 22.14.0)
+NODE_BACKSLASH_OUTPUTS = [
+    (r"[\0]", r"[\0]"),  # was a NUL byte
+    (r"[\x01]", r"[\x01]"),  # was U+0001
+    (r"[\n]", r"[\n]"),  # was a newline
+    (r"[\t]", r"[\t]"),  # was a tab
+    (r"[\1]", r"[\1]"),  # was group 1
+    (r"[\g<1>]", r"[\g<1>]"),  # was group 1
+    (r"[\g<x>]", r"[\g<x>]"),  # was IndexError: unknown group
+    (r"[\u0041]", r"[\u0041]"),  # was "A"
+    (r"[\N{DIGIT ONE}]", r"[\N{DIGIT ONE}]"),  # was "1"
+    (r"[\q]", r"[\q]"),  # was regex.error: bad escape \q
+    (r"[\\]", r"[\\]"),  # was a single backslash
+    (r"[\]", r"[\]"),
+    (r"[\$1]", r"[\a]"),  # was the literal text "\g<1>"
+    (r"C:\path\$1", r"C:\path\a"),  # was regex.error: bad escape \p
+]
+
+
+class HelperBackslashTests(SimpleTestCase):
+    def test_backslash_zero_is_literal_not_a_nul_byte(self):
+        result = regex.sub("(a)", convert_js_numbered_backreferences(r"[\0]"), "a")
+        self.assertEqual(result, r"[\0]")
+        self.assertNotIn("\x00", result)
+
+    def test_backslash_sequences_read_exactly_as_javascript_does(self):
+        for template, expected in NODE_BACKSLASH_OUTPUTS:
+            with self.subTest(template=template):
+                result = regex.sub(
+                    "(a)", convert_js_numbered_backreferences(template), "a"
+                )
+                self.assertEqual(result, expected)
+
+
+class GetTransformedCredentialsBackslashTests(TestCase):
+    def _account(self, search, replace):
+        account = M3UAccount.objects.create(
+            name="452 backslash account",
+            server_url="http://host.example:8080",
+            username="myuser",
+            password="mypass",
+        )
+        profile = account.profiles.get(is_default=True)
+        profile.search_pattern = search
+        profile.replace_pattern = replace
+        profile.save()
+        return account
+
+    def test_get_transformed_credentials_backslash_zero_is_literal(self):
+        account = self._account("myuser", r"\0-X")
+
+        _, username, password = get_transformed_credentials(account)
+
+        self.assertEqual(username, r"\0-X")
+        self.assertEqual(password, "mypass")
+
+    def test_get_transformed_credentials_named_group_still_substitutes(self):
+        account = self._account("(?<u>myuser)", "$<u>2")
+
+        _, username, _ = get_transformed_credentials(account)
+
+        self.assertEqual(username, "myuser2")
+
+
+class RenameBackslashTests(TestCase):
+    """The auto-sync rename and its preview both go through the helper."""
+
+    @classmethod
+    def setUpTestData(cls):
+        from apps.accounts.models import User
+
+        cls.admin = User.objects.create_superuser(
+            username="admin_452_rename", password="pw", user_level=10
+        )
+        cls.account = M3UAccount.objects.create(
+            name="452 Rename Provider",
+            server_url="http://example.com/test.m3u",
+        )
+
+    def _group(self, name, find, replace):
+        group = ChannelGroup.objects.create(name=name)
+        ChannelGroupM3UAccount.objects.create(
+            m3u_account=self.account,
+            channel_group=group,
+            enabled=True,
+            auto_channel_sync=True,
+            auto_sync_channel_start=1000,
+            custom_properties={
+                "name_regex_pattern": find,
+                "name_replace_pattern": replace,
+            },
+        )
+        Stream.objects.create(
+            name="Alpha Channel",
+            url=f"http://example.com/{name}.m3u8",
+            m3u_account=self.account,
+            channel_group=group,
+            tvg_id=f"{name}-0",
+            last_seen=timezone.now(),
+        )
+        return group
+
+    def _preview(self, group_name, find, replace):
+        from rest_framework.test import APIClient
+
+        client = APIClient()
+        client.force_authenticate(user=self.admin)
+        return client.get(
+            "/api/channels/streams/regex-preview/",
+            {"channel_group": group_name, "find": find, "replace": replace},
+        )
+
+    def test_rename_sync_keeps_a_backslash_literal(self):
+        group = self._group("G452Sync", "(Alpha)", r"[\0]$1")
+
+        result = sync_auto_channels(
+            self.account.id,
+            scan_start_time=(timezone.now() - timezone.timedelta(minutes=1)).isoformat(),
+        )
+
+        self.assertEqual(result.get("status"), "ok", result)
+        names = list(
+            Channel.objects.filter(
+                auto_created_by=self.account, channel_group=group
+            ).values_list("name", flat=True)
+        )
+        self.assertEqual(names, [r"[\0]Alpha Channel"])
+
+    def test_rename_preview_backslash_named_group_is_literal_not_a_500(self):
+        self._group("G452Preview", "(Alpha)", r"\g<x>")
+
+        response = self._preview("G452Preview", "(Alpha)", r"\g<x>")
+
+        self.assertEqual(response.status_code, 200)
+        self.assertEqual(
+            response.data["find_matches"],
+            [{"before": "Alpha Channel", "after": r"\g<x> Channel"}],
+        )
diff --git a/apps/proxy/tests/test_next_source_edges.py b/apps/proxy/tests/test_next_source_edges.py
index 005f3e9..96ebf35 100644
--- a/apps/proxy/tests/test_next_source_edges.py
+++ b/apps/proxy/tests/test_next_source_edges.py
@@ -114,6 +114,50 @@ class TransformUrlBackreferenceTests(SimpleTestCase):
         self.assertNotIn("\x01", result)
 
 
+class TransformUrlBackslashTests(SimpleTestCase):
+    r"""#452: a backslash in replace_pattern is literal text, as in JavaScript.
+
+    Every expected value was recorded from Node 22.14.0 as
+    ``url.replace(new RegExp(search, "g"), replace)``. Before #452, ``\0``
+    reached Python's template parser as an octal escape and put a NUL byte
+    into the stream URL, and ``\1`` was read as group 1.
+    """
+
+    def test_transform_url_backslash_zero_is_literal_not_a_nul_byte(self):
+        from apps.proxy.next_source import transform_url
+
+        result = transform_url("http://host/p", r"(host)", r"[\0]$1")
+
+        self.assertEqual(result, r"http://[\0]host/p")
+        self.assertNotIn("\x00", result)
+
+    def test_transform_url_backslash_sequences_read_as_javascript_does(self):
+        from apps.proxy.next_source import transform_url
+
+        for replace, expected in [
+            (r"[\1]", r"[\1]"),
+            (r"[\x01]", r"[\x01]"),
+            (r"[\g<x>]", r"[\g<x>]"),
+            (r"[\$1]", r"[\a]"),
+        ]:
+            with self.subTest(replace=replace):
+                self.assertEqual(transform_url("a", r"(a)", replace), expected)
+
+    def test_transform_url_named_group_still_substitutes(self):
+        from apps.proxy.next_source import transform_url
+
+        # $<name> is rewritten after the backslashes are doubled, so the
+        # \g<name> it produces is not itself escaped into literal text.
+        self.assertEqual(
+            transform_url("http://host/p", r"(?<host>host)", "$<host>2"),
+            "http://host2/p",
+        )
+        self.assertEqual(
+            transform_url("http://host/p", r"(?<host>host)", r"\$<host>"),
+            r"http://\host/p",
+        )
+
+
 class OrderAlternatesFromCurrentTests(SimpleTestCase):
     def test_a_current_stream_id_missing_from_ordered_ids_returns_unrotated(self):
         from apps.proxy.next_source import order_alternates_from_current
diff --git a/apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py b/apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py
index 85a0285..2f5f518 100644
--- a/apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py
+++ b/apps/proxy/vod_proxy/tests/test_transform_url_backreferences.py
@@ -23,3 +23,23 @@ class TransformUrlBackreferencesTests(SimpleTestCase):
 
         self.assertEqual(result, "$0$0")
         self.assertNotIn("\x00", result)
+
+    def test_vod_transform_backslash_zero_is_literal_not_a_nul_byte(self):
+        # #452: "http://host/p".replace(/(host)/g, "[\\0]$1") in Node 22.14.0.
+        m3u_profile = SimpleNamespace(search_pattern=r"(host)", replace_pattern=r"[\0]$1")
+
+        result = _transform_url("http://host/p", m3u_profile)
+
+        self.assertEqual(result, r"http://[\0]host/p")
+        self.assertNotIn("\x00", result)
+
+    def test_vod_transform_named_group_still_substitutes(self):
+        # #452: $<name> must be rewritten after the backslashes are doubled,
+        # or the \g<name> it produces is escaped into literal text.
+        m3u_profile = SimpleNamespace(
+            search_pattern=r"(?<host>host)", replace_pattern="$<host>2"
+        )
+
+        result = _transform_url("http://host/p", m3u_profile)
+
+        self.assertEqual(result, "http://host2/p")
```
<!-- END APPENDIX B -->
