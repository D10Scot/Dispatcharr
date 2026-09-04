# Phase 1 PR 2 — TTFB + SPA-Three-Segment Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two E2E regression guards Phase 1's spec requires before PR 4 touches any
routing — a time-to-first-byte ceiling through nginx and a guard against the XC three-segment
route silently swallowing an SPA deep link — plus the stale-doc corrections the spec assigns to
this PR, all verified against `main`'s current single-process shape.

**Architecture:** Two new `@contract` Playwright tests land in the existing `streaming` project
and exercise behaviour that PR 4 does not change (nginx's unbuffered `/proxy/` passthrough; the
shared Django urlconf both processes will run under D1). Verifying the second test against the
tree surfaced a real gap the spec did not anticipate — see § Spec amendments — so this plan adds
one Task fixing it, entirely inside `dispatcharr/urls.py`, before writing the test that pins it.
Doc corrections (`e2e/README.md`, `CLAUDE.md`) land in the same PR because PR 2 is the first PR to
touch either.

**Tech Stack:** Playwright + TypeScript (`e2e/`), Django's `SimpleTestCase` + `django.urls.resolve`
for the routing unit test, the repo's Docker test-hook containers.

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 2 — `migration/phase1-ttfb-test`.

**Branch:** `migration/phase1-ttfb-test` (worktree `.worktrees/phase1-pr2`), off `main`.

**Setup:**

```bash
cd /Users/dion/git/Dispatcharr
git fetch origin main
git worktree add .worktrees/phase1-pr2 -b migration/phase1-ttfb-test origin/main
cd .worktrees/phase1-pr2
```

## Spec amendments made by this plan (apply to the spec in the same PR that implements them)

1. **PR 2 gains a Task fixing a routing gap the spec did not describe.** The spec says the
   SPA-three-segment test is "written before PR 4's routing change exists, on the current
   single-process shape, so it is a real regression guard rather than a test written to match the
   code" (currently spec lines 838-840), and states the same claim twice more, in different words,
   elsewhere: the § Decisions table's D7 row says "SPA deep links that happen to be three segments
   with no trailing slash still fall to the XC regex and are served correctly by the relay (D1);
   PR 2's test pins that" (currently spec line 428), and § Architecture's "three-segment regex
   trap" paragraph repeats it — "SPA deep links stay in it, are answered correctly by the relay
   because the urlconf is identical (D1), and are pinned by PR 2's test" (currently spec lines
   544-545). All three read as if the described behaviour already holds on `main`.

   Verified against the tree it does not. `dispatcharr/urls.py:40-44` registers
   `path("<str:username>/<str:password>/<str:channel_id>", stream_xc, name="xc_stream_endpoint")`
   ahead of the SPA catch-all (`path("<path:unused_path>", ...)`, `urls.py:70`), and Django's
   `str` converter matches any non-`/` segment, so it captures **every** three-segment,
   no-trailing-slash URI, not only genuine Xtream credentials:

   ```
   $ resolve('/settings/a/b')   -> apps.proxy.live_proxy.views.view {'username': 'settings', 'password': 'a', 'channel_id': 'b'}
   ```

   `stream_xc` (`apps/proxy/live_proxy/views.py:778`) then does
   `user = get_object_or_404(User, username=username)` as its first statement. For any username
   that isn't a real user, this raises `Http404`; DRF's `exception_handler`
   (`rest_framework/views.py`, verified in this worktree's container) converts `Http404` straight
   into a `Response(..., status=404)` **inside the view's own `dispatch()`** and returns it —
   the exception never reaches Django's core exception handling, so it cannot fall through to the
   SPA catch-all or a `handler404` (none is defined in this repo). A three-segment SPA-shaped path
   therefore 404s today, not "served correctly."

   This can't be fixed inside `apps/proxy/live_proxy/` without violating the spec's own Goal
   ("without rewriting a line of `apps/proxy/live_proxy/`"), and it can't be fixed with a
   `handler404` either, because the exception is absorbed before Django's root handler ever sees
   it. The fix that stays outside `apps/proxy/live_proxy/` entirely is narrowing the URL pattern
   itself: real Xtream clients only ever send a numeric channel id, optionally with an extension
   (`stream_xc` does `pathlib.Path(channel_id).suffix` / `.stem`, then `int(channel_id)`), so
   constraining the URL pattern's `channel_id` segment to that shape removes non-numeric
   three-segment paths from the pattern's reach without touching XC semantics for any real
   request. Verified end-to-end against this worktree's `dispatcharr/urls.py` with the resolver
   patched in-process (not committed — verification only):

   ```
   /settings/a/b          -> django.views.generic.base.view {'unused_path': 'settings/a/b'}   (SPA, was 404)
   /settings/example/page -> django.views.generic.base.view {'unused_path': 'settings/example/page'}
   /user/pass/12345       -> apps.proxy.live_proxy.views.view {'channel_id': '12345', ...}     (unchanged)
   /user/pass/12345.ts    -> apps.proxy.live_proxy.views.view {'channel_id': '12345.ts', ...}  (unchanged)
   /live/user/pass/12345  -> apps.proxy.live_proxy.views.view {'channel_id': '12345', ...}      (unchanged)
   ```

   Task 1 below makes that change. It does not fully close the shape collision — an SPA route
   whose last segment happens to be numeric (none exist in `frontend/src/App.jsx` today) would
   still match — the same residual, accepted ambiguity D7 already names for the nginx-level regex.
   No `apps/proxy/live_proxy/`, `vod_proxy/` or `apps/timeshift/` file changes.

   **No three-segment SPA route exists today.** `frontend/src/App.jsx:152-166` is entirely
   single-segment routes (`/channels`, `/sources`, `/guide`, `/dvr`, `/stats`, `/plugins`,
   `/connect`, `/users`, `/settings`, `/logos`, `/vods`) plus the two-segment `/plugins/browse`
   (`:158-160`); `:169` adds `/login`; `:172` is the `*` catch-all. So this test — and Task 1's fix
   — guard the SPA catch-all mechanism and any future three-segment deep link, not a page that is
   broken for a real user today.

   The spec itself needs correcting to match this, since PR 0 (#164) already merged it: Task 1
   below rewrites `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` in three
   places — the § Decisions D7 row (currently line 428), the § Architecture "three-segment regex
   trap" paragraph's repeat of the same claim (currently lines 544-545), and the PR 2 bullet
   (currently lines 837-840) — so the spec states the gap and the fix instead of asserting
   behaviour the tree doesn't have. That file is edited as part of Task 1, in the same commit as
   the `urls.py`/`utils.py` fix it documents.

2. **`e2e/COVERAGE.md` is out of scope for this PR**, despite the plan-writer brief naming it as
   something to verify. The spec's § Documentation assigns "`e2e/COVERAGE.md` rows for TTFB,
   Django-down, bounded relay restart, the authorize matrix and the modular role split" to **PR 8**
   (spec line 1330-1331), not PR 2. This plan does not touch `COVERAGE.md`.

## Global Constraints

- **TTFB ceiling is N ≤ 10 s, chosen, not measured** (spec, PR 2): it is the threshold past which
  the assertion stops telling a live stream from nginx spooling the response to disk
  (`docker/nginx.conf`'s `uwsgi_buffering off` on `/proxy/`, CLAUDE.md § Architecture) — a tighter
  N buys nothing that failure mode needs. The test hardcodes `10_000` ms; the implementing run
  records the measured value in the PR description, per the spec's own instruction.
- **Every new `test()` carries exactly one of `@contract`/`@characterization`** as its
  details-object second argument (`docs/adr/0002-e2e-test-taxonomy.md`, enforced by
  `e2e/tests/guards/tags.spec.ts`). Both new tests here are `@contract`.
- **No line of `apps/proxy/live_proxy/`, `vod_proxy/` or `apps/timeshift/`'s streaming path is
  rewritten** (spec Goal). Task 1's fix lives entirely outside `apps/proxy/`: `dispatcharr/urls.py`
  plus one exported constant in `dispatcharr/utils.py`.
- **Neither new spec file needs a grey-box capability.** Nothing here imports `greybox/redis`,
  the `instance` fixture, `node:child_process`, or writes `/api/core/settings/` — no
  `e2e/tests/guards/allowlist.ts` edit is needed.
- **`e2e/**/*.ts` edits are checked by `tsc --noEmit`** in `e2e/` (blocking hook) — run it after
  writing each spec file.
- **`*tests/test_*.py` edits run the whole `tests` package** (PostToolUse hook, Redis flushed
  first) — Task 1's new file triggers this automatically.
- **Any `*.py` edit is checked by `scripts/check_credential_logging.py`** — Task 1 logs nothing.
- **`dispatcharr/` is in `_SHARED_PATH_PREFIXES`** (`dispatcharr/test_discovery.py:11`): both
  Task 1's commit gate and CI's `backend-tests.yml` matrix run **all 16 backend labels**, not just
  `tests`, because `dispatcharr/urls.py` is a shared path. Baseline 16/16, ~1,787 tests, ~34s
  (CLAUDE.md § Test hooks).
- **`Stage and commit in separate Bash calls`.** The `PreToolUse` hook on `Bash(git commit*)`
  matches the Bash **command text** on every `git commit*` invocation, regardless of the message
  content — a call that both stages and commits is blocked whatever the message says. Write every
  commit message to a scratch file with the Write tool and commit with `git commit -F <msgfile>`.
- **Branch must start with `migration/`** so the full E2E + Lifecycle gate applies (CLAUDE.md §
  Testing, "Full E2E runs") — every Playwright project runs, not the changed-paths-gated subset.
  Already satisfied: `migration/phase1-ttfb-test`.
- **`e2e/COVERAGE.md` is not touched here** — see § Spec amendments, item 2.

## Done criteria (from the spec)

- [ ] Both specs pass in the `streaming` project on `main`'s current shape —
      `cd e2e && E2E_BASE_URL=http://localhost:$DISPATCHARR_E2E_PORT npx playwright test --project=streaming -g "time to first byte|SPA-shaped"`.
- [ ] `E2E result` green in CI on the PR.
- [ ] `e2e/tests/guards/tags.spec.ts` passes (each new `test()` carries exactly one tag) —
      `cd e2e && npx playwright test --project=guards`.
- [ ] **`CLAUDE.md` corrected:** § Testing, "five projects" → thirteen and "eight injectable
      faults" → twelve; the greybox-quarantine sentence naming the deleted
      `quarantine.spec.ts` corrected to name `e2e/tests/guards/allowlist.ts` +
      `capabilities.spec.ts`.
- [ ] `e2e/README.md:104`/`:111` corrected to name `e2e/tests/guards/allowlist.ts` +
      `capabilities.spec.ts`; `e2e/README.md:780` corrected — the live Main ruleset already
      requires `Lifecycle result`.
- [ ] *(this plan's addition)* The routing unit test in Task 1 passes, and the full `tests`
      package still passes at its current count plus five —
      `docker exec ... /dispatcharrpy/bin/python manage.py test --keepdb tests -v1`.
- [ ] *(this plan's addition)* `Backend result` green, **all 16 labels**, not just `tests` —
      `dispatcharr/urls.py` is in `_SHARED_PATH_PREFIXES`
      (`dispatcharr/test_discovery.py:11`), so both the commit gate and CI's `backend-tests.yml`
      matrix run the full 16-label suite for this PR (baseline 16/16, ~34s).
- [ ] *(this plan's addition)* `E2E result` runs in **full mode** — every Playwright project, not
      the changed-paths-gated subset — because the branch is `migration/phase1-ttfb-test`
      (CLAUDE.md § Testing, "Full E2E runs").

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent):
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr2 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr2 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr2/.claude/hooks/start-test-container.sh`
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr2 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr2 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr2/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr2 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr2 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr2/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr2 /dispatcharrpy/bin/python manage.py test --keepdb tests -v1`
5. Frontend: N/A for this PR (no `frontend/` change). E2E typecheck:
   `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr2/e2e && npm ci && npx tsc --noEmit`. A
   full Playwright project run needs the AIO image built from this worktree (`e2e/README.md`); use
   a distinct container/port/volume/network so the shared `dispatcharr-e2e` stack is untouched,
   and never pass `--reset`:
   ```bash
   cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr2
   DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr2 \
   DISPATCHARR_E2E_PORT=19191 \
   DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr2-data \
   DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr2-net \
   ./scripts/e2e_up.sh
   cd e2e && npm ci && npx playwright install --with-deps chromium
   E2E_BASE_URL=http://localhost:19191 npx playwright test --project=guards
   E2E_BASE_URL=http://localhost:19191 npx playwright test --project=streaming -g "time to first byte|SPA-shaped"
   cd .. && DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr2 DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr2-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr2-net ./scripts/e2e_up.sh --down
   ```
6. If the container cannot start, say so in the task report: the work is then unverified, not
   verified.

## File Structure

```
dispatcharr/utils.py                                    MODIFY: export XC_STREAM_ID_PATTERN, the
                                                         shape _XC_STREAM_ID_RE already uses (:99),
                                                         shared with urls.py instead of duplicated
dispatcharr/urls.py                                    MODIFY: narrow the XC 3-segment channel_id
                                                         segment to XC_STREAM_ID_PATTERN (:35-44),
                                                         so a same-shaped SPA path falls to the
                                                         catch-all
tests/test_urls_xc_three_segment.py                     NEW: unit test pinning the narrowed pattern
docs/superpowers/specs/2026-09-04-phase1-process-       MODIFY: correct the D7 row (:428), its
  split-design.md                                       repeat in the regex-trap paragraph
                                                         (:544-545), and the PR 2 bullet (:837-840)
                                                         to state the gap and fix Task 1 makes, not
                                                         behaviour already present
e2e/tests/streaming/time-to-first-byte.spec.ts           NEW: @contract TTFB-through-nginx test
e2e/tests/streaming/spa-three-segment-route.spec.ts      NEW: @contract SPA-shaped-route test
e2e/README.md                                            MODIFY: correct the quarantine-file lines
                                                         (:101-113) and the Lifecycle-result line
                                                         (:780-786)
CLAUDE.md                                                MODIFY: correct project/fault counts and
                                                         the quarantine sentence (:134, :136)
```

### Task 1: Narrow the XC three-segment root pattern so it stops swallowing SPA deep links

**Files:**
- Modify: `dispatcharr/utils.py` (lines 93-99) — export the shared pattern
- Modify: `dispatcharr/urls.py` (lines 35-44) — build both `re_path`s from it
- Create: `tests/test_urls_xc_three_segment.py`
- Modify: `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (lines 428, 544-545,
  837-840) — correct the spec to state the gap and this fix

**Interfaces:**
- Consumes: `apps.proxy.live_proxy.views.stream_xc` (unchanged signature); Django's
  `re_path` (already imported at `urls.py:2`).
- Produces: `dispatcharr.utils.XC_STREAM_ID_PATTERN: str` — the un-anchored regex fragment for a
  real Xtream stream id (digits, optionally with an extension). `dispatcharr/utils.py`'s own
  `_XC_STREAM_ID_RE` (used by `redact_url`) is rebuilt from it (`rf"\A{XC_STREAM_ID_PATTERN}\Z"`)
  instead of duplicating the shape, and `dispatcharr/urls.py`'s two `re_path`s build their
  `channel_id` group from the same constant, so the URL resolver and the log-redaction path can
  never disagree about what counts as a credential-bearing path.
- Import direction verified safe: `dispatcharr/urls.py` importing from `dispatcharr/utils.py` adds
  no cycle — `dispatcharr/utils.py`'s only non-stdlib/non-Django import is `core.models`
  (`utils.py:11`); nothing in it imports `dispatcharr.urls`.
- The URL names `xc_live_stream_endpoint` and `xc_stream_endpoint` are unchanged (verified unused
  by `reverse()` anywhere in `apps/`, `frontend/`, `docker/`), so no caller is affected.

- [ ] **Step 1: Write the failing routing test**

  `tests/test_urls_xc_three_segment.py`:

  ```python
  """dispatcharr/urls.py must route a three-segment path to the Xtream stream_xc
  view only when the final segment is a plausible channel id (digits, optionally
  with an extension) — never for an arbitrary SPA-shaped deep link of the same
  three-segment, no-trailing-slash shape. See docs/superpowers/specs/
  2026-09-04-phase1-process-split-design.md's "three-segment regex trap" (D7)
  and this plan's Task 1 for why: stream_xc's get_object_or_404(User, ...) is
  the first statement in the view, and Http404 never escapes DRF's own
  exception_handler to reach Django's catch-all, so the URL pattern itself is
  the only lever outside apps/proxy/live_proxy/.
  """

  from django.test import SimpleTestCase
  from django.urls import resolve

  from dispatcharr.utils import redact_url


  class XcThreeSegmentRoutingTests(SimpleTestCase):
      def test_numeric_channel_id_still_resolves_to_stream_xc(self):
          match = resolve("/user/pass/12345")
          self.assertEqual(match.url_name, "xc_stream_endpoint")
          self.assertEqual(match.kwargs["channel_id"], "12345")

      def test_numeric_channel_id_with_extension_still_resolves_to_stream_xc(self):
          match = resolve("/user/pass/12345.ts")
          self.assertEqual(match.url_name, "xc_stream_endpoint")
          self.assertEqual(match.kwargs["channel_id"], "12345.ts")

      def test_live_prefixed_numeric_channel_id_still_resolves_to_stream_xc(self):
          match = resolve("/live/user/pass/12345")
          self.assertEqual(match.url_name, "xc_live_stream_endpoint")
          self.assertEqual(match.kwargs["channel_id"], "12345")

      def test_non_numeric_three_segment_path_falls_to_spa_catch_all(self):
          match = resolve("/settings/example/page")
          self.assertIsNone(match.url_name)
          self.assertEqual(match.kwargs, {"unused_path": "settings/example/page"})

      def test_resolver_and_redact_url_agree_on_credential_shape(self):
          # Both consumers build their regex from the same
          # dispatcharr.utils.XC_STREAM_ID_PATTERN (Step 2), so a path either
          # both treat as an XC credential or neither does.
          spa_path = "/settings/example/page"
          xc_path = "/user/pass/12345.ts"

          self.assertIsNone(resolve(spa_path).url_name)
          self.assertEqual(redact_url(spa_path), spa_path)  # nothing to mask

          match = resolve(xc_path)
          self.assertEqual(match.url_name, "xc_stream_endpoint")
          self.assertNotEqual(redact_url(xc_path), xc_path)  # username/password masked
  ```

  Run:
  `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr2 /dispatcharrpy/bin/python manage.py test --keepdb tests.test_urls_xc_three_segment -v2`
  Expected: FAIL — `test_non_numeric_three_segment_path_falls_to_spa_catch_all` and
  `test_resolver_and_redact_url_agree_on_credential_shape` both fail on their first assertion,
  because `/settings/example/page` currently resolves to `xc_stream_endpoint`
  (`{'username': 'settings', 'password': 'example', 'channel_id': 'page'}`), not the catch-all.
  The other three pass already (they pin unchanged behaviour); `redact_url`'s half of the fifth
  test also already passes — `_XC_STREAM_ID_RE` is unrelated to the URL resolver today, which is
  exactly the duplication Step 2 removes.

- [ ] **Step 2: Export the shared pattern from `dispatcharr/utils.py`**

  In `dispatcharr/utils.py`, replace lines 93-99:

  ```python
  # The XC root route is `/<username>/<password>/<channel_id>` with no prefix to
  # key off (dispatcharr/urls.py `xc_stream_endpoint`). It is only recognised as
  # credential-bearing when the path is exactly three segments and the last looks
  # like a stream id — a number with an optional extension. That shape can also
  # match a non-Xtream path, in which case two harmless segments get masked;
  # over-masking a log line is the safe direction of that trade.
  _XC_STREAM_ID_RE = re.compile(r"\A\d+(?:\.[A-Za-z0-9]+)?\Z")
  ```

  with:

  ```python
  # The XC root route is `/<username>/<password>/<channel_id>` with no prefix to
  # key off (dispatcharr/urls.py `xc_stream_endpoint`). It is only recognised as
  # credential-bearing when the path is exactly three segments and the last looks
  # like a stream id — a number with an optional extension. That shape can also
  # match a non-Xtream path, in which case two harmless segments get masked;
  # over-masking a log line is the safe direction of that trade.
  #
  # Shared with dispatcharr/urls.py's XC URL patterns (xc_stream_endpoint /
  # xc_live_stream_endpoint), so the URL resolver and this redaction path can
  # never disagree about what counts as a real Xtream channel id. Anchors are
  # the caller's job: this file wraps it in \A...\Z, urls.py in ^...$.
  XC_STREAM_ID_PATTERN = r"\d+(?:\.[A-Za-z0-9]+)?"

  _XC_STREAM_ID_RE = re.compile(rf"\A{XC_STREAM_ID_PATTERN}\Z")
  ```

  This is a pure refactor — `_XC_STREAM_ID_RE`'s compiled pattern is byte-identical, so
  `redact_url`'s behaviour does not change.

  Run:
  `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr2 /dispatcharrpy/bin/python manage.py test --keepdb tests.test_redaction -v2`
  Expected: PASS, unchanged — proves the refactor didn't touch `redact_url`'s behaviour before
  Step 3 changes the URL resolver's.

- [ ] **Step 3: Narrow the two URL patterns**

  In `dispatcharr/urls.py`, add the import after line 10 (`from apps.timeshift.views import
  timeshift_proxy, timeshift_proxy_query`):

  ```python
  from dispatcharr.utils import XC_STREAM_ID_PATTERN
  ```

  Then replace lines 35-44:

  ```python
      path(
          "live/<str:username>/<str:password>/<str:channel_id>",
          stream_xc,
          name="xc_live_stream_endpoint",
      ),
      path(
          "<str:username>/<str:password>/<str:channel_id>",
          stream_xc,
          name="xc_stream_endpoint",
      ),
  ```

  with:

  ```python
      # channel_id is constrained to XC_STREAM_ID_PATTERN (dispatcharr/utils.py) —
      # the shape a real Xtream client sends: digits, optionally with an
      # extension (stream_xc does pathlib.Path(channel_id).stem / .suffix, then
      # int(channel_id)) — so a same-shaped SPA deep link (e.g.
      # /settings/example/page) falls through to the SPA catch-all instead of
      # stream_xc's get_object_or_404(User, ...) 404. See docs/superpowers/
      # plans/2026-09-04-phase1-pr2-ttfb-test.md's Spec amendments for why this
      # can't be fixed inside stream_xc itself.
      re_path(
          rf"^live/(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})$",
          stream_xc,
          name="xc_live_stream_endpoint",
      ),
      re_path(
          rf"^(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})$",
          stream_xc,
          name="xc_stream_endpoint",
      ),
  ```

  Run: the same `manage.py test --keepdb tests.test_urls_xc_three_segment -v2` command as Step 1.
  Expected: PASS — all five tests green.

- [ ] **Step 4: Run the whole `tests` package to confirm no regression**

  Run:
  `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr2 /dispatcharrpy/bin/python manage.py test --keepdb tests -v1`
  Expected: PASS, same baseline count for the `tests` package plus the 5 new tests, 0 failures.
  Because `dispatcharr/` is in `_SHARED_PATH_PREFIXES` (`dispatcharr/test_discovery.py:11`), the
  commit gate in Step 6 and CI's `backend-tests.yml` matrix run **all 16 backend labels** for this
  change, not just `tests` — this command checks the one label that actually exercises the new
  code; the gate/CI run is the full-suite proof (baseline 16/16, ~34s).

- [ ] **Step 5: Correct the spec to describe the gap and this fix**

  Three replacements in `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md`. Anchor
  each on the quoted sentence, not the line number — line numbers drift and are given here only as
  "currently" pointers, verified against this worktree at the time this plan was written.

  **(a) The § Decisions table's D7 row** (currently line 428) ends with this sentence — replace it
  in place, leaving the rest of the row (the `**bold**` decision and its rationale) untouched:

  ```
  SPA deep links that happen to be three segments with no trailing slash still fall to the XC regex and are served correctly by the relay (D1); PR 2's test pins that.
  ```

  with:

  ```
  SPA deep links that happen to be three segments with no trailing slash reach the same urlconf as the XC regex, courtesy of D1 — but D1 alone does not make them serve correctly: `stream_xc`'s `get_object_or_404(User, ...)` 404s on any non-matching username, and DRF's exception handler absorbs that `Http404` before Django's catch-all ever sees it. PR 2 narrows the XC pattern's `channel_id` segment (`dispatcharr/urls.py`, sharing the shape `dispatcharr/utils.py` already used privately for log redaction, now exported as `XC_STREAM_ID_PATTERN`) to the numeric-with-optional-extension shape a real Xtream stream id has, so a same-shaped SPA path falls through to the SPA catch-all instead; PR 2's test pins the fixed behaviour.
  ```

  **(b) § Architecture's "three-segment regex trap" paragraph** repeats the same claim in
  different words (currently lines 544-545) — replace only this sentence, leaving the rest of the
  paragraph (the `/hdhr`/`/output/` `^~` discussion and the closing "What must never happen"
  sentence) untouched:

  ```
  SPA deep links stay in it, are answered correctly by the relay because the urlconf is identical (D1), and are pinned by PR 2's test.
  ```

  with:

  ```
  SPA deep links stay in it and reach the same urlconf (D1), but D1 alone does not serve them: PR 2 narrows the XC pattern's `channel_id` to the numeric stream-id shape so they fall to Django's catch-all, and PR 2's test pins that.
  ```

  **(c) The PR 2 section's second bullet** (currently lines 837-840):

  ```
  - New E2E spec, same project, `@contract`: a three-segment root URI that is a valid SPA deep link
    still serves the SPA shell, not a 404. Written **before** PR 4's routing change exists, on the
    current single-process shape, so it is a real regression guard rather than a test written to
    match the code.
  ```

  with:

  ```
  - **`dispatcharr/urls.py`'s XC three-segment pattern (`xc_stream_endpoint`/`xc_live_stream_endpoint`) is
    narrowed** to the numeric-with-optional-extension `channel_id` shape a real Xtream client sends
    — the shape `dispatcharr/utils.py` already used privately for log redaction, now exported as
    `XC_STREAM_ID_PATTERN` and shared rather than duplicated. Verified against the tree: today the
    bare `<str:username>/<str:password>/<str:channel_id>` pattern captures every three-segment,
    no-trailing-slash URI ahead of the SPA catch-all, and `stream_xc`'s
    `get_object_or_404(User, ...)` 404s inside DRF's own exception handling before Django's root
    handler — and therefore the SPA catch-all — ever sees it. No `apps/proxy/live_proxy/` change.
  - New E2E spec, same project, `@contract`: a three-segment root URI that is a valid SPA deep link
    still serves the SPA shell, not a 404. Written **before** PR 4's routing change exists, on the
    current single-process shape, so it is a real regression guard — and, given the routing gap
    just above, this PR's own fix for it, not a test written to match code that already worked.
  ```

  No other line in the spec changes; § Testing and § Requirements already describe this test
  correctly and cite no behaviour this edit contradicts.

- [ ] **Step 6: Commit**

  ```bash
  git add dispatcharr/utils.py dispatcharr/urls.py tests/test_urls_xc_three_segment.py docs/superpowers/specs/2026-09-04-phase1-process-split-design.md
  ```

  Write the message with the Write tool to a scratch file — the `PreToolUse` hook on
  `Bash(git commit*)` matches the Bash command text of every `git commit*` call, so `git add` and
  `git commit` must be separate Bash calls regardless of what the message says — then:

  ```bash
  git commit -F <msgfile>
  ```

  Message body:

  ```
  fix(routing): stop the XC 3-segment pattern swallowing SPA deep links

  dispatcharr/urls.py's bare `<user>/<pass>/<channel_id>` pattern matched
  every three-segment, no-trailing-slash URI ahead of the SPA catch-all.
  stream_xc's get_object_or_404(User, ...) 404s on any non-matching
  username, and DRF's exception_handler absorbs that Http404 inside the
  view's own dispatch() before Django's root handler ever sees it, so
  nothing could fall through to the SPA shell. Constraining channel_id to
  XC_STREAM_ID_PATTERN (dispatcharr/utils.py) — the numeric-with-optional-
  extension shape a real Xtream client sends, and the same shape
  redact_url already used for log masking — removes the collision for
  every SPA route that doesn't end in a bare digit, without touching
  apps/proxy/live_proxy/, and without a second copy of the pattern.

  Also corrects docs/superpowers/specs/2026-09-04-phase1-process-split-
  design.md's D7 sentence and PR 2 bullet, which both read as though this
  behaviour already held on main before this fix landed.

  Needed so Phase 1 PR 2's SPA-three-segment E2E guard test can actually
  pass on main's current shape, per that spec's PR 2 Done criterion.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```

### Task 2: Add the time-to-first-byte contract test

**Files:**
- Create: `e2e/tests/streaming/time-to-first-byte.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect`, `expectTsAligned`, `TS_PACKET_SIZE` from `../../fixtures`;
  `lockedProfile` from `./helpers` (both already exported/verified in `e2e/fixtures/index.ts` and
  `e2e/tests/streaming/helpers.ts`).

- [ ] **Step 1: Write the test**

  `e2e/tests/streaming/time-to-first-byte.spec.ts`:

  ```typescript
  import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
  import { lockedProfile } from './helpers';

  /**
   * Time to first byte through nginx (Phase 1 PR 2).
   *
   * nginx's `/proxy/` location runs with `uwsgi_buffering off` (docker/nginx.conf,
   * CLAUDE.md § Architecture) specifically so a live TS response streams
   * straight through instead of being spooled to disk first.
   *
   * N = 10s is the CHOSEN ceiling, not a measurement: it's the spec's own
   * spooling-detection threshold (docs/superpowers/specs/2026-09-04-phase1-
   * process-split-design.md, PR 2), not a characterisation of normal
   * latency. Past it the assertion stops telling a live stream apart from
   * nginx spooling the whole response to disk before forwarding it, which is
   * the only failure this test exists to catch — a tighter N would buy
   * nothing that failure mode needs, since real TTFB (logged below) sits
   * nowhere near the ceiling. It must exist before PR 4 changes any nginx
   * routing and keep passing after it — nothing about this assertion depends
   * on which process answers the request.
   *
   * The measured elapsed time is logged unconditionally below; the
   * implementing PR copies that number, plus this 10s ceiling, into its
   * description per the spec's own instruction.
   */
  const TTFB_CEILING_MS = 10_000;

  test(
    'the first TS packet through nginx arrives within the TTFB ceiling',
    { tag: '@contract' },
    async ({ upstream, seed, api, streamClient }) => {
      const scenario = await upstream.scenario({
        channels: [{ id: 1, name: 'G4 TTFB', tvgId: 'g4-ttfb.e2e', logo: null }],
        rate: 20,
      });
      const proxy = await lockedProfile(api, 'Proxy');
      const { channel } = await seed.upstreamChannel(scenario, {
        channelIds: [1],
        streamProfileId: proxy.id,
      });

      const started = Date.now();
      await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
      const packet = await streamClient.readPackets(1);
      const elapsedMs = Date.now() - started;

      console.log(`[ttfb] first TS packet through nginx (:9191): ${elapsedMs}ms (ceiling ${TTFB_CEILING_MS}ms)`);

      expect(packet.byteLength).toBe(TS_PACKET_SIZE);
      expectTsAligned(packet);
      expect(
        elapsedMs,
        `first TS packet took ${elapsedMs}ms through nginx; ceiling is ${TTFB_CEILING_MS}ms`
      ).toBeLessThanOrEqual(TTFB_CEILING_MS);
    }
  );
  ```

  Run: `cd e2e && npx tsc --noEmit` (also the blocking PostToolUse hook for this file).
  Expected: no type errors.

- [ ] **Step 2: Run it against a live container**

  Run (against the distinct-port stack from § Test environment, step 5):
  `cd e2e && E2E_BASE_URL=http://localhost:19191 npx playwright test --project=streaming -g "time to first byte"`
  Expected: PASS. Note the `[ttfb] first TS packet ...` console line — that measured value goes
  into the PR description alongside the `10_000` ms ceiling, per the spec's instruction for this
  PR.

- [ ] **Step 3: Commit**

  ```bash
  git add e2e/tests/streaming/time-to-first-byte.spec.ts
  ```

  Write the message to a scratch file, then:

  ```bash
  git commit -F <msgfile>
  ```

  Message body:

  ```
  test(e2e): pin time-to-first-byte through nginx before PR 4's routing change

  Adds an @contract regression guard in the streaming project: the first
  TS packet through nginx (:9191) must arrive within 10s, the ceiling past
  which the measurement stops telling a live stream apart from nginx
  spooling the response to disk. Measured <MEASURED>ms on this run.

  docs/superpowers/specs/2026-09-04-phase1-process-split-design.md, PR 2.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```

  Replace `<MEASURED>` with the console-logged value from Step 2 before writing the file.

### Task 3: Add the SPA-three-segment-route contract test

**Files:**
- Create: `e2e/tests/streaming/spa-three-segment-route.spec.ts`

**Interfaces:**
- Consumes: `test`, `expect` from `../../fixtures` (Playwright's built-in `request` and `baseURL`
  fixtures, re-exported the same way every other spec in this directory uses them — see
  `e2e/tests/lifecycle/restart-persistence.spec.ts:31` for the `baseURL` destructure and
  `e2e/tests/seeded/api-fixture.spec.ts:5` / `network-acl.spec.ts:158` for the relative-path
  `request.get()` pattern this test reuses).

- [ ] **Step 1: Write the test**

  `e2e/tests/streaming/spa-three-segment-route.spec.ts`:

  ```typescript
  import { test, expect } from '../../fixtures';

  /**
   * The XC three-segment root form (`/<user>/<pass>/<channel_id>`) has no
   * distinguishing URL prefix (docs/superpowers/specs/2026-09-04-phase1-
   * process-split-design.md, "The three-segment regex trap", D7). Task 1 of
   * this PR narrows dispatcharr/urls.py's `channel_id` segment to the shape a
   * real Xtream client sends (digits, optionally with an extension), so a
   * same-shaped SPA deep link now falls through to the SPA catch-all instead
   * of stream_xc's 404. This test pins that outcome on the CURRENT
   * single-process shape, before PR 4 gives `/` its own nginx location — a
   * real regression guard, not a test written to match routing that does not
   * exist yet. `/settings/example/page` is three segments, no trailing
   * slash, and its last segment is not numeric, so it cannot collide with a
   * genuine Xtream channel id either before or after Task 1's fix.
   */
  test(
    'a three-segment SPA-shaped route still serves the SPA shell, not a 404',
    { tag: '@contract' },
    async ({ request }) => {
      const response = await request.get('/settings/example/page');

      expect(response.status()).toBe(200);
      expect(response.headers()['content-type'] ?? '').toContain('text/html');

      const body = await response.text();
      expect(body).toContain('<div id="root">');
    }
  );
  ```

  Run: `cd e2e && npx tsc --noEmit`.
  Expected: no type errors.

- [ ] **Step 2: Run it against a live container**

  Run: `cd e2e && E2E_BASE_URL=http://localhost:19191 npx playwright test --project=streaming -g "SPA-shaped"`
  Expected: PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add e2e/tests/streaming/spa-three-segment-route.spec.ts
  ```

  Write the message to a scratch file, then:

  ```bash
  git commit -F <msgfile>
  ```

  Message body:

  ```
  test(e2e): pin the SPA three-segment route against the XC regex trap

  Adds an @contract regression guard in the streaming project: a
  three-segment, no-trailing-slash path that is not a valid Xtream
  credential must serve the SPA shell (200, text/html, <div id="root">),
  not stream_xc's 404. Depends on Task 1's narrowing of
  dispatcharr/urls.py's XC pattern in this same PR.

  docs/superpowers/specs/2026-09-04-phase1-process-split-design.md, PR 2,
  "the regex trap D7 identifies."

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```

### Task 4: Correct the stale doc lines this PR is responsible for

**Files:**
- Modify: `e2e/README.md` (lines 101-113, 780-786)
- Modify: `CLAUDE.md` (lines 134, 136)

**Interfaces:** None — prose only.

- [ ] **Step 1: Correct `e2e/README.md`'s quarantine-file paragraph (`:101-113`)**

  Replace:

  ```markdown
  **The set of specs allowed to reach for grey-box Redis access is a checked
  allowlist, not a comment asking politely.** `e2e/fixtures/greybox/redis.ts`
  exports `GREYBOX_ALLOWLIST`, and
  `e2e/tests/streaming-greybox/quarantine.spec.ts` walks every `.ts` file under
  `e2e/`, greps each for an import of `greybox/redis`, and asserts the set it
  finds matches the allowlist exactly — in either direction: a new grey-box
  import that isn't listed fails the meta-test, and a stale allowlist entry for
  a file that no longer imports it fails the same way. That is what happened
  when G4's ownership-lease flagship (`ownership-lease.spec.ts`) was deleted as
  an unprovable gap (see `COVERAGE.md`'s Streaming/G4 rows) — its allowlist
  entry had to go with it, or `quarantine.spec.ts` would fail on a name that no
  longer exists. A convention written down in this file would rot silently the
  same way; this one fails CI instead.
  ```

  with:

  ```markdown
  **The set of specs allowed to reach for grey-box Redis access is a checked
  allowlist, not a comment asking politely.** `e2e/fixtures/greybox/redis.ts`
  is the sanctioned way a test reaches Redis, and `e2e/tests/guards/allowlist.ts`
  exports the `GREYBOX_REDIS` capability naming every file allowed to import
  it. `e2e/tests/guards/capabilities.spec.ts` parses every spec under `e2e/`
  (AST, not a grep) and asserts the files that actually import `greybox/redis`
  match that list exactly — in either direction: a new grey-box import that
  isn't listed fails the check, and a stale allowlist entry for a file that no
  longer imports it fails the same way. That is what happened when G4's
  ownership-lease flagship (`ownership-lease.spec.ts`) was deleted as an
  unprovable gap (see `COVERAGE.md`'s Streaming/G4 rows) — its allowlist entry
  had to go with it, or `capabilities.spec.ts` would fail on a name that no
  longer exists. `capabilities.spec.ts` also polices three sibling
  capabilities the original `quarantine.spec.ts` did not — container
  lifecycle, subprocess execution and container introspection — for the same
  reason: a convention written down in this file would rot silently; a
  checked allowlist fails CI instead.
  ```

- [ ] **Step 2: Correct `e2e/README.md`'s Lifecycle-result paragraph (`:780-786`)**

  Replace:

  ```markdown
  `Lifecycle result` is **not** in the Main ruleset yet. G12 has taken both bash
  suites to green in CI — `test-puid-pgid.sh` at 135 passed / 0 failed / 1
  skipped (`readonly_rootfs`, which needs more tmpfs mounts and is expected) and
  `test-tls-postgres.sh` at 33 passed / 0 failed — so the reason not to add it
  is gone, but a ruleset is a repository setting rather than a file in the
  diff. **Adding it is the maintainer's follow-up.** Until that happens, a green
  `Lifecycle result` is a signal, not a gate.
  ```

  with:

  ```markdown
  `Lifecycle result` **is** in the Main ruleset. G12 took both bash suites to
  green in CI — `test-puid-pgid.sh` at 135 passed / 0 failed / 1 skipped
  (`readonly_rootfs`, which needs more tmpfs mounts and is expected) and
  `test-tls-postgres.sh` at 33 passed / 0 failed — and the maintainer's
  follow-up landed: the live ruleset requires `Lifecycle result` on every PR,
  the same way it requires `E2E result`, `Backend result` and `Frontend
  result`. A green `Lifecycle result` is a gate, not just a signal.
  ```

- [ ] **Step 3: Correct `CLAUDE.md`'s § Testing project/fault counts (`:134`)**

  In the sentence beginning `**E2E exists now**`, replace:

  ```
  a Playwright suite in `e2e/` (five projects: `pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox` — each its own CI job and container) runs against a shared, API-seeded AIO container (ADR `docs/adr/0001`), with `e2e-upstream/` providing a fake provider image with eight injectable faults.
  ```

  with:

  ```
  a Playwright suite in `e2e/` (thirteen projects: `bootstrap`, `guards`, `pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`, `frontend`, `dvr`, `lifecycle`, `lifecycle-upgrade`, `lifecycle-restore`, `lifecycle-scheduling` — most run their own CI job and container; `guards` is static analysis over the suite's own source and needs neither) runs against a shared, API-seeded AIO container (ADR `docs/adr/0001`), with `e2e-upstream/` providing a fake provider image with twelve injectable faults.
  ```

- [ ] **Step 4: Correct `CLAUDE.md`'s quarantine sentence (`:136`)**

  Replace:

  ```
  **The e2e suite quarantines its Redis coupling on purpose.** `e2e/fixtures/greybox/redis.ts` is the only sanctioned way a test reaches Redis; `tests/streaming-greybox/quarantine.spec.ts` enforces an importer allowlist with a test that fails naming the offender — an assertion, not a convention.
  ```

  with:

  ```
  **The e2e suite quarantines its Redis coupling on purpose.** `e2e/fixtures/greybox/redis.ts` is the only sanctioned way a test reaches Redis; `e2e/tests/guards/allowlist.ts` + `e2e/tests/guards/capabilities.spec.ts` enforce an importer allowlist across four capabilities (grey-box Redis, container lifecycle, subprocess execution, container introspection), each with a test that fails naming the offender — an assertion, not a convention.
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add e2e/README.md CLAUDE.md
  ```

  Write the message to a scratch file, then:

  ```bash
  git commit -F <msgfile>
  ```

  Message body:

  ```
  docs: correct stale e2e project/fault counts and the quarantine references

  e2e/README.md still named the deleted tests/streaming-greybox/quarantine.spec.ts
  and understated the live ruleset's Lifecycle result requirement.
  CLAUDE.md still said "five projects" / "eight injectable faults" (now
  thirteen and twelve) and the same stale quarantine file. Corrects both to
  match the tree, per docs/superpowers/specs/2026-09-04-phase1-process-
  split-design.md's PR 2 documentation requirement.

  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015etUXzEMh4fD6y6na9ZGaf
  ```
